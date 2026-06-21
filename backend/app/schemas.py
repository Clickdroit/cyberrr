"""
Pydantic schemas for request/response validation.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request schemas ──────────────────────────────────────────────────────────

class ScanRequest(BaseModel):
    target: str = Field(..., min_length=1, max_length=512, description="Target to investigate")
    target_type: Optional[str] = Field("auto", description="auto | username | email | phone")


class LoginRequest(BaseModel):
    password: str


# ── Response schemas ─────────────────────────────────────────────────────────

class ToolStatusSchema(BaseModel):
    tool_name: str
    status: str  # pending | running | completed | failed | skipped
    sites_found: int = 0
    sites_checked: int = 0
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class EntitySchema(BaseModel):
    entity_type: str
    value: str
    occurrences: int
    confidence: float
    sources: List[str] = []


class AccountSchema(BaseModel):
    """A social account found by any tool."""
    site_name: str
    url: str
    category: str  # social | gaming | tech | forum | dating | other
    source_tool: str
    metadata: Dict[str, Any] = {}


class CorrelationSummary(BaseModel):
    """Aggregated intelligence from all tools."""
    firstnames: Dict[str, int] = {}
    lastnames: Dict[str, int] = {}
    locations: Dict[str, int] = {}
    emails_found: List[str] = []
    phones_found: List[str] = []
    bio_keywords: Dict[str, int] = {}
    accounts: List[AccountSchema] = []
    total_accounts: int = 0
    top_identity_guess: Optional[str] = None
    confidence_score: float = 0.0


class ScanResponse(BaseModel):
    scan_id: str
    target: str
    target_type: str
    status: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    tools: List[ToolStatusSchema] = []
    summary: Optional[CorrelationSummary] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = []

    model_config = {"from_attributes": True}


class ScanListItem(BaseModel):
    scan_id: str
    target: str
    target_type: str
    status: str
    created_at: datetime
    total_accounts: int = 0
    notes: Optional[str] = None
    tags: Optional[List[str]] = []

    model_config = {"from_attributes": True}


class ScanMetadataUpdate(BaseModel):
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


# ── WebSocket event schemas ──────────────────────────────────────────────────


class WSEvent(BaseModel):
    """Payload pushed via WebSocket to the frontend."""
    event: str  # tool_update | scan_complete | scan_failed | progress
    scan_id: str
    data: Dict[str, Any] = {}


class SettingsUpdate(BaseModel):
    hibp_api_key: Optional[str] = None
    proxy_url: Optional[str] = None
    ghunt_cookies: Optional[str] = None


class SettingsResponse(BaseModel):
    hibp_api_key_configured: bool
    proxy_url: str
    ghunt_cookies_configured: bool
