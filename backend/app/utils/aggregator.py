"""
Data aggregation and correlation engine.
Parses raw output from all OSINT tools and extracts/correlates entities:
firstnames, lastnames, locations, emails, phone numbers, bio keywords.
Uses regex + a curated name/city list for lightweight NER without heavy ML.
"""
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

# ── Static datasets ───────────────────────────────────────────────────────────

# Common French/English/Spanish first names (abbreviated — expanded at runtime)
COMMON_FIRSTNAMES = {
    # French
    "maxime", "théo", "mathieu", "lucas", "hugo", "arthur", "ethan", "noah",
    "thomas", "raphaël", "léo", "enzo", "tom", "baptiste", "alexis", "florian",
    "mattéo", "matteo", "antoine", "pierre", "paul", "louis", "nathan", "julien",
    "robin", "vincent", "alexandre", "nicolas", "clément", "romain", "kevin",
    "emma", "jade", "léa", "chloé", "alice", "inès", "camille", "manon",
    "lucie", "marie", "juliette", "sarah", "laura", "sophie", "amélie", "clara",
    "élise", "elisa", "eva", "zoé", "charlotte", "anaïs", "pauline",
    # English
    "james", "john", "robert", "michael", "william", "david", "richard",
    "joseph", "charles", "thomas", "christopher", "daniel", "matthew", "anthony",
    "mark", "donald", "steven", "paul", "andrew", "ken", "joshua", "kevin",
    "brian", "george", "edward", "jessica", "jennifer", "ashley", "sarah",
    "emily", "samantha", "amanda", "melissa", "deborah", "stephanie", "rebecca",
    "rachel", "laura", "helen", "lisa", "anna", "kate", "olivia", "grace",
    # Spanish/Italian
    "carlos", "miguel", "juan", "jose", "diego", "pablo", "alex", "mario",
    "sofia", "isabella", "valentina", "camila", "lucia", "elena", "sara",
}

# Common world cities for location extraction
COMMON_CITIES = {
    "paris", "lyon", "marseille", "toulouse", "nice", "nantes", "strasbourg",
    "montpellier", "bordeaux", "lille", "rennes", "reims", "grenoble", "dijon",
    "london", "manchester", "birmingham", "glasgow", "liverpool", "edinburgh",
    "new york", "los angeles", "chicago", "houston", "phoenix", "san francisco",
    "miami", "seattle", "boston", "denver", "atlanta", "dallas",
    "berlin", "munich", "hamburg", "cologne", "frankfurt", "amsterdam",
    "madrid", "barcelona", "rome", "milan", "brussels", "vienna", "zurich",
    "montreal", "toronto", "vancouver", "sydney", "melbourne", "tokyo", "osaka",
    "dubai", "singapore", "hong kong", "bangkok", "jakarta",
    "france", "uk", "usa", "germany", "spain", "italy", "canada", "australia",
    "belgium", "switzerland", "netherlands", "japan",
}

# Regex patterns
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
PHONE_RE = re.compile(r"(?:\+\d{1,3}[-.\s]?)?\(?\d{1,4}\)?[-.\s]?\d{2,4}[-.\s]?\d{2,4}[-.\s]?\d{0,4}")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-]\d{2}[/\-]\d{2}|"
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
    r"\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

# Social network categories
CATEGORY_MAP = {
    # Gaming
    "twitch": "gaming", "steam": "gaming", "battlenet": "gaming",
    "epicgames": "gaming", "xbox": "gaming", "playstation": "gaming",
    "roblox": "gaming", "minecraft": "gaming", "leagueoflegends": "gaming",
    "valorant": "gaming", "chess": "gaming", "lichess": "gaming",
    "speedrun": "gaming", "itch": "gaming", "gamebanana": "gaming",
    # Social Media
    "instagram": "social", "facebook": "social", "twitter": "social",
    "x.com": "social", "tiktok": "social", "snapchat": "social",
    "pinterest": "social", "tumblr": "social", "mastodon": "social",
    "bluesky": "social", "threads": "social", "vk": "social",
    # Tech / Dev
    "github": "tech", "gitlab": "tech", "bitbucket": "tech",
    "stackoverflow": "tech", "hackernews": "tech", "dev.to": "tech",
    "codepen": "tech", "replit": "tech", "kaggle": "tech",
    "leetcode": "tech", "hackerrank": "tech", "npm": "tech",
    "pypi": "tech", "dockerhub": "tech", "productHunt": "tech",
    # Forums
    "reddit": "forum", "discord": "forum", "4chan": "forum",
    "quora": "forum", "medium": "forum", "wordpress": "forum",
    "blogger": "forum", "deviantart": "forum", "flickr": "forum",
    # Dating / Social-lite
    "tinder": "dating", "bumble": "dating", "okcupid": "dating",
    "badoo": "dating", "meetic": "dating",
    # Music / Media
    "spotify": "music", "soundcloud": "music", "lastfm": "music",
    "youtube": "media", "vimeo": "media", "dailymotion": "media",
    "mixcloud": "music", "bandcamp": "music",
    # Professional
    "linkedin": "professional", "xing": "professional", "viadeo": "professional",
}


def categorize_site(site_name: str, url: str) -> str:
    """Determine the category of a social platform."""
    name_lower = site_name.lower().replace(" ", "").replace("-", "")
    url_lower = url.lower()
    for key, category in CATEGORY_MAP.items():
        if key in name_lower or key in url_lower:
            return category
    return "other"


def extract_text_entities(text: str) -> Dict[str, List[str]]:
    """
    Extract named entities from a text string.
    Returns dict with keys: firstnames, locations, emails, phones, urls, dates.
    """
    if not text:
        return {}

    text_lower = text.lower()
    words = re.findall(r"\b[a-zA-Zàâäéèêëïîôùûüÿœæç]+\b", text_lower)

    firstnames = [w for w in words if w in COMMON_FIRSTNAMES]
    locations = []

    # Check single words
    for word in words:
        if word in COMMON_CITIES:
            locations.append(word.title())

    # Check two-word combos (e.g., "new york", "hong kong")
    for i in range(len(words) - 1):
        two_word = f"{words[i]} {words[i+1]}"
        if two_word in COMMON_CITIES:
            locations.append(two_word.title())

    emails = EMAIL_RE.findall(text)
    phones = PHONE_RE.findall(text)
    urls = URL_RE.findall(text)
    dates = DATE_RE.findall(text)

    return {
        "firstnames": [fn.title() for fn in set(firstnames)],
        "locations": list(set(locations)),
        "emails": [e.lower() for e in set(emails)],
        "phones": list(set(phones)),
        "urls": list(set(urls)),
        "dates": list(set(dates)),
    }


class DataAggregator:
    """
    Aggregates and correlates results from multiple OSINT tools.
    Maintains running counters for all entity types.
    """

    def __init__(self):
        self.firstname_counter: Counter = Counter()
        self.lastname_counter: Counter = Counter()
        self.location_counter: Counter = Counter()
        self.email_set: set = set()
        self.phone_set: set = set()
        self.bio_keyword_counter: Counter = Counter()
        self.accounts: List[Dict[str, Any]] = []
        self._seen_urls: set = set()

    def ingest_tool_results(self, tool_name: str, results: Dict[str, Any]):
        """
        Process raw results from a tool and update internal counters.
        Each tool emits results in a standardized format.
        """
        # Handle accounts/profiles list
        for account in results.get("accounts", []):
            url = account.get("url", "")
            if url and url not in self._seen_urls:
                self._seen_urls.add(url)
                site = account.get("site_name", "Unknown")
                self.accounts.append({
                    "site_name": site,
                    "url": url,
                    "category": categorize_site(site, url),
                    "source_tool": tool_name,
                    "metadata": account.get("metadata", {}),
                })

        # Process metadata/profile fields
        metadata = results.get("metadata", {})
        bio = metadata.get("bio", "") or ""
        name = metadata.get("name", "") or ""
        location = metadata.get("location", "") or ""

        # Extract from name field
        if name:
            parts = name.strip().split()
            if len(parts) >= 1:
                fn = parts[0].lower()
                if fn in COMMON_FIRSTNAMES:
                    self.firstname_counter[parts[0].title()] += 2  # Higher weight
            if len(parts) >= 2:
                self.lastname_counter[parts[-1].title()] += 1

        # Extract from location field
        if location:
            loc_lower = location.lower()
            for city in COMMON_CITIES:
                if city in loc_lower:
                    self.location_counter[city.title()] += 2

        # Extract from bio
        if bio:
            entities = extract_text_entities(bio)
            for fn in entities.get("firstnames", []):
                self.firstname_counter[fn] += 1
            for loc in entities.get("locations", []):
                self.location_counter[loc] += 1
            for email in entities.get("emails", []):
                self.email_set.add(email)
            for phone in entities.get("phones", []):
                self.phone_set.add(phone)
            # Bio keywords (exclude stopwords)
            stopwords = {"the", "a", "an", "is", "in", "on", "at", "for", "with",
                        "i", "me", "my", "and", "or", "of", "to", "it", "its"}
            words = re.findall(r"\b[a-z]{4,}\b", bio.lower())
            for w in words:
                if w not in stopwords and w not in COMMON_FIRSTNAMES:
                    self.bio_keyword_counter[w] += 1

        # Direct email/phone fields
        for email in results.get("emails", []):
            self.email_set.add(email.lower())
        for phone in results.get("phones", []):
            self.phone_set.add(phone)

    def build_summary(self) -> Dict[str, Any]:
        """Build the final aggregated summary dict."""
        # Top identity guess
        top_firstname = (
            self.firstname_counter.most_common(1)[0][0]
            if self.firstname_counter else None
        )
        top_location = (
            self.location_counter.most_common(1)[0][0]
            if self.location_counter else None
        )

        identity_parts = []
        if top_firstname:
            identity_parts.append(top_firstname)
        if top_location:
            identity_parts.append(f"({top_location})")
        top_identity = " ".join(identity_parts) if identity_parts else None

        # Confidence: based on data richness
        data_points = (
            len(self.firstname_counter) * 2
            + len(self.location_counter)
            + len(self.email_set) * 3
            + len(self.accounts)
        )
        confidence = min(1.0, data_points / 20)

        return {
            "firstnames": dict(self.firstname_counter.most_common(10)),
            "lastnames": dict(self.lastname_counter.most_common(10)),
            "locations": dict(self.location_counter.most_common(10)),
            "emails_found": sorted(self.email_set),
            "phones_found": sorted(self.phone_set),
            "bio_keywords": dict(self.bio_keyword_counter.most_common(20)),
            "accounts": self.accounts,
            "total_accounts": len(self.accounts),
            "top_identity_guess": top_identity,
            "confidence_score": round(confidence, 2),
        }
