"""
Results API — aggregated data endpoints for the dashboard.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import CorrelatedEntity, Scan, get_db
from app.schemas import CorrelationSummary

router = APIRouter(prefix="/api", tags=["results"])


@router.get("/scan/{scan_id}/summary", response_model=CorrelationSummary)
async def get_summary(scan_id: str, db: AsyncSession = Depends(get_db)):
    """Return the full aggregated summary for a completed scan."""
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()

    if not scan:
        raise HTTPException(status_code=404, detail="Scan not found")
    if scan.status not in ("completed", "failed"):
        raise HTTPException(status_code=202, detail="Scan still in progress")
    if not scan.summary:
        return CorrelationSummary()

    summary = scan.summary
    return CorrelationSummary(
        firstnames=summary.get("firstnames", {}),
        lastnames=summary.get("lastnames", {}),
        locations=summary.get("locations", {}),
        emails_found=summary.get("emails_found", []),
        phones_found=summary.get("phones_found", []),
        bio_keywords=summary.get("bio_keywords", {}),
        accounts=summary.get("accounts", []),
        total_accounts=summary.get("total_accounts", 0),
        top_identity_guess=summary.get("top_identity_guess"),
        confidence_score=summary.get("confidence_score", 0.0),
    )


@router.get("/scan/{scan_id}/entities")
async def get_entities(scan_id: str, db: AsyncSession = Depends(get_db)):
    """Return all correlated entities for a scan."""
    result = await db.execute(
        select(CorrelatedEntity)
        .where(CorrelatedEntity.scan_id == scan_id)
        .order_by(CorrelatedEntity.occurrences.desc())
    )
    entities = result.scalars().all()

    return [
        {
            "type": e.entity_type,
            "value": e.value,
            "occurrences": e.occurrences,
            "confidence": e.confidence,
            "sources": e.sources or [],
        }
        for e in entities
    ]
