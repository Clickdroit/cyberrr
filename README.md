# 🔭 OSINT Hub

**Hub d'Investigation OSINT Automatisé** — Plateforme self-hosted déployable via Docker sur Ubuntu/DigitalOcean.

> ⚠️ **Usage légal uniquement.** Cet outil est conçu pour des investigations légales et éthiques. Respectez les CGU des plateformes et les réglementations RGPD/CCPA.

---

## 🚀 Démarrage Rapide

### 1. Prérequis
- Docker Engine ≥ 24.0
- Docker Compose ≥ 2.20
- 2 GB RAM minimum recommandé

### 2. Configuration

```bash
# Cloner le repo
git clone https://github.com/Clickdroit/cyberrr osint-hub
cd osint-hub

# Copier et éditer le fichier d'environnement
cp .env.example .env
nano .env
```

**Variables obligatoires dans `.env` :**
| Variable | Description |
|----------|-------------|
| `ACCESS_PASSWORD` | Votre mot de passe d'accès au site |
| `SECRET_KEY` | Clé secrète pour les cookies (32+ chars) |

Générer une clé secrète :
```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 3. Lancement

```bash
docker compose up --build -d
```

L'application est accessible sur **http://your-vps-ip**

---

## 🏗️ Architecture

```
osint-hub/
├── backend/                 # FastAPI + Celery workers
│   ├── app/
│   │   ├── main.py          # App FastAPI + WebSocket
│   │   ├── auth.py          # Auth middleware (single password)
│   │   ├── celery_app.py    # Configuration Celery
│   │   ├── database.py      # SQLAlchemy + SQLite
│   │   ├── schemas.py       # Pydantic models
│   │   ├── api/             # Routes REST
│   │   │   ├── scan.py
│   │   │   └── results.py
│   │   ├── workers/         # Modules OSINT
│   │   │   ├── orchestrator.py
│   │   │   ├── maigret_worker.py
│   │   │   ├── sherlock_worker.py
│   │   │   ├── holehe_worker.py
│   │   │   ├── ghunt_worker.py
│   │   │   └── scraper_worker.py
│   │   └── utils/
│   │       ├── aggregator.py      # Moteur de corrélation
│   │       ├── input_detector.py  # Détection auto du type
│   │       └── redis_pubsub.py    # WebSocket bridge
│   └── Dockerfile
├── frontend/                # SPA HTML/JS/CSS
│   ├── index.html
│   ├── css/style.css
│   └── js/
│       ├── app.js
│       └── websocket.js
├── nginx/nginx.conf         # Reverse proxy
├── docker-compose.yml
└── .env.example
```

### Services Docker

| Service | Image | Rôle |
|---------|-------|------|
| `frontend` | nginx:1.25-alpine | Serveur frontend + reverse proxy |
| `backend` | custom Python 3.12 | API FastAPI + WebSocket |
| `worker` | custom Python 3.12 | Celery — exécution des outils OSINT |
| `redis` | redis:7-alpine | Broker Celery + Pub/Sub WebSocket |

---

## 🛠️ Outils OSINT Intégrés

### 👤 Recherche par Pseudonyme
| Outil | Méthode | Sites couverts |
|-------|---------|----------------|
| **Maigret** | API Python native (async) | 3000+ (avec métadonnées) |
| **Sherlock** | subprocess + JSON | 400+ (vitesse brute) |
| **Web Scraper** | httpx + BeautifulSoup | Pages des profils trouvés |

### ✉️ Recherche par Email
| Outil | Méthode | Ce qu'il fait |
|-------|---------|---------------|
| **Holehe** | API Python async | Vérifie 120+ services sans alerte |
| **GHunt** | subprocess (nécessite cookies) | Intelligence Google/Gmail/Maps |
| **Web Scraper** | httpx + BeautifulSoup | Enrichissement des profils trouvés |

---

## 🌐 Configuration GHunt (optionnel)

GHunt nécessite une authentification Google :

```bash
# Entrer dans le container worker
docker compose exec worker bash

# Lancer l'authentification interactive
python -m ghunt login

# Suivre les instructions dans le navigateur
# Les cookies seront sauvegardés automatiquement
```

Sans cette configuration, GHunt est automatiquement désactivé (les autres outils fonctionnent normalement).

---

## 🔒 Sécurité

- **Authentification** : Mot de passe unique via cookie signé (itsdangerous + HMAC)
- **Session** : 7 jours, HttpOnly, SameSite=Lax
- **Headers** : X-Frame-Options, X-Content-Type-Options, CSP
- **Réseau** : Tous les services sur un réseau Docker interne isolé
- **Redis** : Non exposé publiquement (port interne uniquement)

### Pour activer HTTPS (recommandé en production)

Option A — Avec Certbot sur le VPS :
```bash
# Installer Nginx + Certbot sur le VPS (en dehors de Docker)
apt install certbot python3-certbot-nginx
certbot --nginx -d votre-domaine.com
# Puis configurer un reverse proxy vers Docker port 80
```

Option B — Modifier `nginx.conf` pour SSL direct dans Docker.

---

## 📡 API REST

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `POST /api/scan` | POST | Lancer un scan |
| `GET /api/scan/{id}` | GET | Statut d'un scan |
| `GET /api/scan/{id}/summary` | GET | Résumé agrégé |
| `GET /api/history` | GET | Historique des scans |
| `DELETE /api/scan/{id}` | DELETE | Supprimer un scan |
| `WS /ws/{id}` | WebSocket | Live feed du scan |
| `POST /auth/login` | POST | Authentification |
| `POST /auth/logout` | POST | Déconnexion |
| `GET /health` | GET | Health check |

Documentation interactive : `http://your-ip/api/docs`

---

## 🔧 Commandes Utiles

```bash
# Voir les logs en temps réel
docker compose logs -f

# Logs d'un service spécifique
docker compose logs -f worker

# Redémarrer après modification du .env
docker compose down && docker compose up -d

# Accéder au shell du worker
docker compose exec worker bash

# Voir les tâches Celery en cours
docker compose exec worker celery -A app.celery_app inspect active

# Backup de la base de données
docker compose exec backend sqlite3 /data/db/osint.db ".backup '/data/db/backup.db'"

# Mettre à jour l'application
git pull
docker compose up --build -d
```

---

## ⚙️ Configuration Avancée

### Modifier le nombre de workers Celery
Dans `docker-compose.yml`, modifier `--concurrency=2` selon votre VPS :
- 1 vCPU : `--concurrency=1`
- 2 vCPU : `--concurrency=2`
- 4 vCPU : `--concurrency=4`

### Changer le port d'exposition
Dans `.env` :
```
PORT=8080
```

---

## 📝 Licence

Usage personnel uniquement. Ne pas redistribuer sans autorisation.
