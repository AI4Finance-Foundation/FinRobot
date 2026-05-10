"""
Database connection module - supports SQLite (local) and PostgreSQL (Cloud SQL)
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Use DATABASE_URL env var for Cloud SQL, fall back to local SQLite
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    # Cloud SQL PostgreSQL
    engine = create_engine(DATABASE_URL, echo=False)
    DATABASE_PATH = None
else:
    # Local SQLite
    DB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(DB_DIR, exist_ok=True)
    DATABASE_PATH = os.path.join(DB_DIR, "finrobot.db")
    DATABASE_URL = f"sqlite:///{DATABASE_PATH}"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        echo=False
    )

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Session:
    """Get database session"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database tables"""
    from .models import Base
    Base.metadata.create_all(bind=engine)
    db_info = DATABASE_PATH or "Cloud SQL"
    print(f"Database initialized at: {db_info}")
