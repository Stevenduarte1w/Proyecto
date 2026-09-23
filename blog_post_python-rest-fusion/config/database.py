from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .settings import settings

# Database configuration
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """Session generator"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
