"""
tests/test_db_integration.py
----------------------------
Integration and unit tests for SQLite database operations and CSV migration utility.
"""
import os
import pytest
import pandas as pd
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from core.db import Base, Trade

# Use in-memory SQLite database for testing
TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

def test_trade_model_creation(db_session):
    # Insert a sample trade
    new_trade = Trade(
        id="test_trade_123",
        timestamp=datetime(2026, 8, 1, 9, 30, 0),
        symbol="TCS",
        direction="LONG",
        qty=10,
        entry_price=3200.50,
        exit_price=3240.20,
        pnl=397.00,
        exit_reason="CLOSED_TARGET",
        entry_time=datetime(2026, 8, 1, 9, 15, 0)
    )
    db_session.add(new_trade)
    db_session.commit()

    # Query trade back
    retrieved = db_session.query(Trade).filter_by(id="test_trade_123").first()
    assert retrieved is not None
    assert retrieved.symbol == "TCS"
    assert retrieved.direction == "LONG"
    assert retrieved.qty == 10
    assert retrieved.entry_price == 3200.50
    assert retrieved.exit_price == 3240.20
    assert retrieved.pnl == 397.00
    assert retrieved.exit_reason == "CLOSED_TARGET"

def test_csv_migration_logic(db_session, tmp_path):
    # Create a temporary CSV file
    csv_file = tmp_path / "trade_history_test.csv"
    df = pd.DataFrame({
        "timestamp": ["2026-08-01 09:30:00"],
        "id": ["migrated_id_999"],
        "symbol": ["INFY"],
        "direction": ["SHORT"],
        "qty": [50],
        "entry_price": [1500.00],
        "exit_price": [1480.00],
        "pnl": [1000.00],
        "exit_reason": ["CLOSED_TARGET"],
        "entry_time": ["2026-08-01 09:15:00"]
    })
    df.to_csv(csv_file, index=False)

    # Patch Path inside migrate_csv_to_sqlite to point to our test CSV file
    with patch("core.db.SessionLocal", return_value=db_session):
        from server import migrate_csv_to_sqlite
        
        with patch("server.Path", return_value=csv_file):
            migrate_csv_to_sqlite()

    # Verify that trade is now in database
    retrieved = db_session.query(Trade).filter_by(id="migrated_id_999").first()
    assert retrieved is not None
    assert retrieved.symbol == "INFY"
    assert retrieved.direction == "SHORT"
    assert retrieved.qty == 50
    assert retrieved.pnl == 1000.00
