import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

# .env file ko load karna
load_dotenv(override=True)

# Default fallback: Agar .env me na mile, to direct sqlite database uthayega
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")

# Engine setup
engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {},
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# FastAPI routes ke liye database session dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()