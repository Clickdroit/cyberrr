"""
Scan API router — POST /api/scan, GET /api/scan/{id}, GET /api/history.
"""
import uuid
from datetime import datetime
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Scan, ScanResult, get_db
from app.schemas import ScanListItem, ScanRequest, ScanResponse, ToolStatusSchema, ScanMetadataUpdate
from app.utils.input_detector import detect_input_type
from app.workers.orchestrator import run_scan

router = APIRouter(prefix="/api", tags=["scans"])


@router.post("/scan", response_model=ScanResponse, status_code=202)
async def create_scan(
    payload: ScanRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a new OSINT scan.
    Returns immediately with a scan_id; use WebSocket /ws/{scan_id} for live updates.
    """
    target = payload.target.strip()
    target_type = payload.target_type or "auto"

    # Auto-detect type
    detected_type = detect_input_type(target) if target_type == "auto" else target_type

    scan_id = str(uuid.uuid4())

    # Create scan record
    scan = Scan(
        id=scan_id,
        target=target,
        target_type=detected_type,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(scan)

    # Create tool result placeholders
    tools_for_type = {
        "username": ["maigret", "sherlock", "whatsmyname", "scraper"],
        "email": ["holehe", "ghunt", "hibp", "scraper"],
        "phone": ["phone_lookup"],
        "unknown": ["maigret", "sherlock", "whatsmyname", "scraper"],
    }
    for tool_name in tools_for_type.get(detected_type, ["maigret", "sherlock"]):
        db.add(ScanResult(
            scan_id=scan_id,
            tool_name=tool_name,
            status="pending",
        ))

    await db.commit()

    # Dispatch Celery task
    run_scan.apply_async(
        kwargs={
            "scan_id": scan_id,
            "target": target,
            "target_type": detected_type,
        },
        task_id=f"scan-{scan_id}",
    )

    # Return initial response
    return ScanResponse(
        scan_id=scan_id,
        target=target,
        target_type=detected_type,
        status="pending",
        created_at=scan.created_at,
        tools=[
            ToolStatusSchema(tool_name=t, status="pending")
            for t in tools_for_type.get(detected_type, ["maigret", "sherlock"])
        ],
        notes=None,
        tags=[],
    )


@router.get("/scan/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: str, db: AsyncSession = Depends(get_db)):
    """Get current state of a scan."""
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()

    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    # Fetch tool results
    tool_results = await db.execute(
        select(ScanResult).where(ScanResult.scan_id == scan_id)
    )
    tools = tool_results.scalars().all()

    return ScanResponse(
        scan_id=scan.id,
        target=scan.target,
        target_type=scan.target_type or "unknown",
        status=scan.status or "pending",
        created_at=scan.created_at,
        completed_at=scan.completed_at,
        tools=[
            ToolStatusSchema(
                tool_name=t.tool_name,
                status=t.status or "pending",
                sites_found=t.sites_found or 0,
                sites_checked=t.sites_checked or 0,
                error_message=t.error_message,
                started_at=t.started_at,
                completed_at=t.completed_at,
            )
            for t in tools
        ],
        summary=scan.summary,
        notes=scan.notes,
        tags=scan.tags or [],
    )


@router.get("/history", response_model=List[ScanListItem])
async def get_history(
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List recent scans."""
    result = await db.execute(
        select(Scan)
        .order_by(Scan.created_at.desc())
        .limit(min(limit, 100))
    )
    scans = result.scalars().all()

    items = []
    for s in scans:
        total = 0
        if s.summary and isinstance(s.summary, dict):
            total = s.summary.get("total_accounts", 0)
        items.append(ScanListItem(
            scan_id=s.id,
            target=s.target,
            target_type=s.target_type or "unknown",
            status=s.status or "pending",
            created_at=s.created_at,
            total_accounts=total,
            notes=s.notes,
            tags=s.tags or [],
        ))

    return items


@router.put("/scan/{scan_id}/metadata", response_model=ScanResponse)
async def update_scan_metadata(
    scan_id: str,
    payload: ScanMetadataUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update notes and tags for a specific scan."""
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()

    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")

    if payload.notes is not None:
        scan.notes = payload.notes.strip()
    if payload.tags is not None:
        scan.tags = payload.tags

    await db.commit()

    # Fetch tool results
    tool_results = await db.execute(
        select(ScanResult).where(ScanResult.scan_id == scan_id)
    )
    tools = tool_results.scalars().all()

    return ScanResponse(
        scan_id=scan.id,
        target=scan.target,
        target_type=scan.target_type or "unknown",
        status=scan.status or "pending",
        created_at=scan.created_at,
        completed_at=scan.completed_at,
        tools=[
            ToolStatusSchema(
                tool_name=t.tool_name,
                status=t.status or "pending",
                sites_found=t.sites_found or 0,
                sites_checked=t.sites_checked or 0,
                error_message=t.error_message,
                started_at=t.started_at,
                completed_at=t.completed_at,
            )
            for t in tools
        ],
        summary=scan.summary,
        notes=scan.notes,
        tags=scan.tags or [],
    )


@router.delete("/scan/{scan_id}", status_code=204)
async def delete_scan(scan_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a scan and all its results."""
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    await db.delete(scan)
    await db.commit()

