"""운영 정리 작업(전체 점검 2-8): 답변 추적 기록 보관 기간."""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models.answer_trace import AnswerTrace
from app.pipeline.tasks import maintenance
from tests.conftest import TEST_DATABASE_URL

SYNC_URL = TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2")
NOW = datetime(2026, 11, 16, 12, 0, 0)


@pytest.fixture
def db():
    engine = create_engine(SYNC_URL)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    session.query(AnswerTrace).delete()
    session.commit()
    yield session
    session.query(AnswerTrace).delete()
    session.commit()
    session.close()
    engine.dispose()


def _trace(db, days_old):
    trace = AnswerTrace(id=uuid4(), query="q", status="DONE", created_at=NOW - timedelta(days=days_old))
    db.add(trace)
    db.commit()
    return trace.id


def test_purge_removes_only_traces_older_than_the_retention(db, monkeypatch):
    monkeypatch.setattr(maintenance, "PURGE_BATCH_SIZE", 2)
    old = [_trace(db, days) for days in (400, 366, 500)]
    kept = [_trace(db, days) for days in (364, 1)]

    deleted = maintenance.purge_answer_traces(db, 365, now=NOW)

    remaining = {row[0] for row in db.query(AnswerTrace.id).all()}
    assert deleted == 3 and remaining == set(kept) and not remaining & set(old)


def test_zero_retention_keeps_everything(db):
    _trace(db, 5000)

    assert maintenance.purge_answer_traces(db, 0, now=NOW) == 0
    assert db.query(AnswerTrace).count() == 1
