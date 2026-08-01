"""
core/db.py
----------
Database initialization and SQLAlchemy schemas for persistent trade storage.
Supports both SQLite and PostgreSQL interchangeably.
"""
import os
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime
from sqlalchemy.orm import sessionmaker, declarative_base
from config.settings import settings

# Ensure the config directory exists for local SQLite storage
os.makedirs("config", exist_ok=True)

# Load connection string from settings (with a robust SQLite fallback)
DATABASE_URL = getattr(settings, "DATABASE_URL", None) or "sqlite:///config/trading_bot.db"

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, index=True)
    symbol = Column(String, index=True)
    direction = Column(String)
    qty = Column(Integer)
    entry_price = Column(Float)
    exit_price = Column(Float)
    pnl = Column(Float)
    exit_reason = Column(String)
    entry_time = Column(DateTime)


def init_db():
    """Create all tables in the database if they do not exist."""
    Base.metadata.create_all(bind=engine)
