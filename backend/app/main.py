"""
FastAPI main application.
Wires together: auth middleware, API routers, WebSocket, static files.
"""
import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth import (
    ACCESS_PASSWORD,
    COOKIE_NAME,
    AuthMiddleware,
    sign_session,
    verify_session,
)
from app.database import init_db
from app.api.scan import router as scan_router
from app.api.results import router as results_router
from app.utils.redis_pubsub import subscribe_to_scan

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FRONTEND_DIR = os.getenv("FRONTEND_DIR", "/app/frontend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup."""
    logger.info("🔍 OSINT Hub starting up...")
    await init_db()
    logger.info("✅ Database initialized")
    yield
    logger.info("👋 OSINT Hub shutting down")


app = FastAPI(
    title="OSINT Hub",
    description="Automated OSINT Investigation Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# ── CORS (restrict to same-origin in production) ─────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restricted by Nginx in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth middleware ───────────────────────────────────────────────────────────
app.add_middleware(AuthMiddleware)

# ── Auth routes ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "osint-hub"}


@app.post("/auth/login")
async def login(request: Request):
    """Validate password and set session cookie."""
    body = await request.json()
    password = body.get("password", "")

    if password != ACCESS_PASSWORD:
        return JSONResponse({"success": False, "message": "Wrong password"}, status_code=401)

    token = sign_session()
    response = JSONResponse({"success": True})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        secure=os.getenv("HTTPS_ENABLED", "false").lower() == "true",
        max_age=60 * 60 * 24 * 7,  # 7 days
    )
    return response


@app.post("/auth/logout")
async def logout():
    """Clear session cookie."""
    response = JSONResponse({"success": True})
    response.delete_cookie(COOKIE_NAME)
    return response


@app.get("/auth/check")
async def auth_check(request: Request):
    """Check if current session is valid."""
    token = request.cookies.get(COOKIE_NAME)
    if token and verify_session(token):
        return {"authenticated": True}
    return JSONResponse({"authenticated": False}, status_code=401)


# ── OSINT API routes ──────────────────────────────────────────────────────────
app.include_router(scan_router)
app.include_router(results_router)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@app.websocket("/ws/{scan_id}")
async def websocket_scan(websocket: WebSocket, scan_id: str):
    """
    WebSocket endpoint for real-time scan progress.
    Subscribes to Redis Pub/Sub channel for the scan_id.
    Sends events until scan_complete or scan_failed is received.
    """
    # Authenticate via cookie
    token = websocket.cookies.get(COOKIE_NAME)
    if not token or not verify_session(token):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"WS connected: {scan_id}")

    try:
        async for event in subscribe_to_scan(scan_id):
            await websocket.send_text(json.dumps(event))

            # Close gracefully after terminal events
            if event.get("event") in ("scan_complete", "scan_failed"):
                await asyncio.sleep(0.5)
                break

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: {scan_id}")
    except Exception as e:
        logger.error(f"WS error for {scan_id}: {e}")
        try:
            await websocket.close(code=1011, reason="Internal error")
        except Exception:
            pass


# ── Frontend static files (served by Nginx in production; fallback here) ─────

# Serve frontend if directory exists (dev mode)
if os.path.isdir(FRONTEND_DIR):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str):
        """Catch-all route serving the SPA for client-side routing."""
        file_path = os.path.join(FRONTEND_DIR, full_path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        # Return index.html for SPA routing
        index = os.path.join(FRONTEND_DIR, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        return JSONResponse({"detail": "Not found"}, status_code=404)
