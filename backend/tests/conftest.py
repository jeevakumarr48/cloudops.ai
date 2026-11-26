"""Test configuration: make the ``backend`` package root importable and give
every test its own empty in-memory database."""

import os
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from core import database  # noqa: E402
from core import models  # noqa: E402,F401  (registers tables)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    database.Base.metadata.create_all(engine)
    database.configure(engine)
    yield engine
    database.reset()
    engine.dispose()
