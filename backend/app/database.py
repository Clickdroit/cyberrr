"""
SQLAlchemy database models and session management.
Uses SQLite with async support via aiosqlite.
"""
import os
from datetime import datetime
from typing import AsyncGenerator

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship

DB_PATH = os.getenv("DB_PATH", "/data/db/osint.db")
DATABASE_URL = f"sqlite+aiosqlite:///{DB_PATH}"

engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False},
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


class Scan(Base):
    """A scan investigation session."""
    __tablename__ = "scans"

    id = Column(String(36), primary_key=True)  # UUID
    target = Column(String(512), nullable=False, index=True)
    target_type = Column(
        Enum("username", "email", "phone", "ip", "domain", "unknown", name="target_type_enum"),
        default="unknown",
    )
    status = Column(
        Enum("pending", "running", "completed", "failed", name="scan_status_enum"),
        default="pending",
    )
    created_at = Column(DateTime, default=func.now())
    completed_at = Column(DateTime, nullable=True)
    summary = Column(JSON, nullable=True)  # Aggregated results JSON
    notes = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)  # List of strings as JSON

    results = relationship("ScanResult", back_populates="scan", cascade="all, delete-orphan")
    entities = relationship("CorrelatedEntity", back_populates="scan", cascade="all, delete-orphan")


class ScanResult(Base):
    """Raw result from a single OSINT tool."""
    __tablename__ = "scan_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(36), ForeignKey("scans.id"), nullable=False, index=True)
    tool_name = Column(String(64), nullable=False)
    status = Column(
        Enum("pending", "running", "completed", "failed", "skipped", name="tool_status_enum"),
        default="pending",
    )
    raw_data = Column(JSON, nullable=True)
    sites_found = Column(Integer, default=0)
    sites_checked = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    scan = relationship("Scan", back_populates="results")


class CorrelatedEntity(Base):
    """
    An entity extracted and correlated across multiple tools.
    Examples: first names, locations, emails, usernames found on profiles.
    """
    __tablename__ = "correlated_entities"

    id = Column(Integer, primary_key=True, autoincrement=True)
    scan_id = Column(String(36), ForeignKey("scans.id"), nullable=False, index=True)
    entity_type = Column(
        Enum("firstname", "lastname", "email", "location", "username",
             "phone", "bio_keyword", "url", "date", name="entity_type_enum"),
        nullable=False,
    )
    value = Column(String(512), nullable=False)
    occurrences = Column(Integer, default=1)
    confidence = Column(Float, default=0.5)
    sources = Column(JSON, nullable=True)  # List of tools that found it

    scan = relationship("Scan", back_populates="entities")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency: async DB session."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Create all tables on startup."""
    # Ensure directory exists
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        
        # Auto-migration schema check for notes and tags columns
        def migrate_schema(connection):
            cursor = connection.connection.cursor()
            cursor.execute("PRAGMA table_info(scans)")
            columns = [row[1] for row in cursor.fetchall()]
            if "notes" not in columns:
                cursor.execute("ALTER TABLE scans ADD COLUMN notes TEXT")
            if "tags" not in columns:
                cursor.execute("ALTER TABLE scans ADD COLUMN tags TEXT")
        
        await conn.run_sync(migrate_schema)

