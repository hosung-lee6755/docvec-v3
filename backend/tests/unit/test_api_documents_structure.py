"""documents/structure.py 엔드포인트(정제/사전/PII/잡/콘텐츠/표) — 실제 Postgres(db_session)."""
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select

from app.api.v1.endpoints.documents import structure as st
from app.core import crypto
from app.db.models.audit_log import AuditLog
from app.db.models.cleaning_rule import CleaningChange, CleaningRule
from app.db.models.dictionary_application import DictionaryApplication
from app.db.models.pii_detection import PiiDetection
from app.db.models.processing_job import ProcessingJob
from tests.unit._docs_api_support import (
    add_doc,
    add_step,
    admin_user,
    assert_http_error,
    doc_with_run,
    owner_user,
    stranger_user,
)
from tests.unit._docs_api_support import db_session  # noqa: F401


# ------------------------------------------------- _resolve_cleaning_rule_name
def test_rule_name_prefers_custom_rule_then_builtin_label_then_raw_key():
    assert st._resolve_cleaning_rule_name("내 규칙", "builtin:quotes") == "내 규칙"
    assert st._resolve_cleaning_rule_name(None, "builtin:quotes") == "따옴표 정규화"
    assert st._resolve_cleaning_rule_name(None, "custom:unknown") == "custom:unknown"
    assert st._resolve_cleaning_rule_name(None, None) is None


# -------------------------------------------------------- cleaning-changes
async def _change(db, doc, run, step, created_at, **fields) -> CleaningChange:
    change = CleaningChange(id=uuid4(), run_id=run.id, step_id=step.id, document_id=doc.id, created_at=created_at, **fields)
    db.add(change)
    await db.flush()
    return change


async def test_cleaning_changes_resolve_names_and_aggregate_counts(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-clean")
    step = await add_step(db_session, run)
    rule = CleaningRule(id=uuid4(), rule_name="전화번호 정리", rule_type="REGEX_REPLACE")
    db_session.add(rule)
    await db_session.flush()
    now = datetime.utcnow()
    await _change(db_session, doc, run, step, now, rule_id=rule.id, rule_key=None, change_count=3)
    await _change(db_session, doc, run, step, now + timedelta(seconds=1), rule_key="builtin:whitespace", change_count=2)
    await _change(db_session, doc, run, step, now + timedelta(seconds=2), rule_key="builtin:whitespace", change_count=5)

    result = await st.list_cleaning_changes(doc.id, db_session, owner_user())

    assert [c["rule_name"] for c in result["changes"]] == ["전화번호 정리", "공백·빈 줄 정리", "공백·빈 줄 정리"]
    assert result["total_changes"] == 10
    assert result["distinct_rule_count"] == 2  # (rule_id,key) 쌍 기준 중복 제거
    assert result["run_id"] == str(run.id)


async def test_cleaning_changes_empty_without_run_404_and_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "s-clean-empty")

    result = await st.list_cleaning_changes(doc.id, db_session, owner_user())

    assert (result["changes"], result["total_changes"], result["distinct_rule_count"], result["run_id"]) == ([], 0, 0, None)
    await assert_http_error(st.list_cleaning_changes(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(st.list_cleaning_changes(doc.id, db_session, stranger_user()), 403)


# ------------------------------------------------- dictionary-applications
async def _application(db, doc, run, step, created_at, reverted=False) -> DictionaryApplication:
    app_row = DictionaryApplication(
        id=uuid4(), run_id=run.id, step_id=step.id, document_id=doc.id, dictionary_type="SYNONYM",
        dictionary_version=1, original_text="AI", normalized_text="인공지능", reverted=reverted, created_at=created_at,
    )
    db.add(app_row)
    await db.flush()
    return app_row


async def test_dictionary_applications_count_pending_reverts(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-dict")
    step = await add_step(db_session, run)
    now = datetime.utcnow()
    first = await _application(db_session, doc, run, step, now, reverted=True)
    second = await _application(db_session, doc, run, step, now + timedelta(seconds=1))

    result = await st.list_dictionary_applications(doc.id, db_session, owner_user())

    assert [a.id for a in result["applications"]] == [first.id, second.id]
    assert result["pending_revert_count"] == 1


async def test_dictionary_applications_empty_404_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "s-dict-empty")

    result = await st.list_dictionary_applications(doc.id, db_session, owner_user())

    assert result["applications"] == [] and result["pending_revert_count"] == 0
    await assert_http_error(st.list_dictionary_applications(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(st.list_dictionary_applications(doc.id, db_session, stranger_user()), 403)


async def test_revert_dictionary_application_marks_reverted(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-revert")
    app_row = await _application(db_session, doc, run, await add_step(db_session, run), datetime.utcnow())

    result = await st.revert_dictionary_application(doc.id, app_row.id, db_session, owner_user())

    assert result.reverted is True


async def test_revert_dictionary_application_404_403_and_other_document(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-revert-g1")
    other = await add_doc(db_session, "s-revert-g2")
    app_row = await _application(db_session, doc, run, await add_step(db_session, run), datetime.utcnow())

    await assert_http_error(st.revert_dictionary_application(uuid4(), app_row.id, db_session, owner_user()), 404)
    await assert_http_error(st.revert_dictionary_application(doc.id, app_row.id, db_session, stranger_user()), 403)
    # 다른 문서의 id로는 이 문서의 적용 이력을 되돌릴 수 없다
    await assert_http_error(st.revert_dictionary_application(other.id, app_row.id, db_session, owner_user()), 404)
    assert app_row.reverted is False


# ------------------------------------------------------------------- pii
async def _pii(db, doc, run, created_at=None, original: str | None = None) -> PiiDetection:
    detection = PiiDetection(
        id=uuid4(), run_id=run.id, document_id=doc.id, entity_type="PHONE", action="MASK",
        masked_value="010-****-****", created_at=created_at or datetime.utcnow(),
        original_encrypted=crypto.encrypt_secret(original) if original else None,
    )
    db.add(detection)
    await db.flush()
    return detection


async def test_pii_list_empty_404_403(db_session):  # noqa: F811
    doc = await add_doc(db_session, "s-pii-empty")

    assert (await st.list_pii_detections(doc.id, db_session, owner_user()))["detections"] == []
    await assert_http_error(st.list_pii_detections(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(st.list_pii_detections(doc.id, db_session, stranger_user()), 403)


async def test_pii_list_returns_detections_in_creation_order(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-pii-list")
    now = datetime.utcnow()
    late = await _pii(db_session, doc, run, now + timedelta(seconds=5))
    early = await _pii(db_session, doc, run, now)

    result = await st.list_pii_detections(doc.id, db_session, owner_user())

    assert [d.id for d in result["detections"]] == [early.id, late.id]


async def test_pii_approve_then_reject_flips_review_state(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-pii-review")
    detection = await _pii(db_session, doc, run)
    user = owner_user()

    approved = await st.approve_pii_detection(doc.id, detection.id, db_session, user)
    assert (str(approved.approved_by), approved.rejected) == (str(user.id), False)
    assert approved.approved_at is not None

    rejected = await st.reject_pii_detection(doc.id, detection.id, db_session, user)
    assert (rejected.rejected, rejected.approved_by, rejected.approved_at) == (True, None, None)


async def test_pii_approve_reject_guards(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-pii-guard")
    other = await add_doc(db_session, "s-pii-guard-other")
    detection = await _pii(db_session, doc, run)

    for endpoint in (st.approve_pii_detection, st.reject_pii_detection):
        await assert_http_error(endpoint(uuid4(), detection.id, db_session, owner_user()), 404)
        await assert_http_error(endpoint(doc.id, uuid4(), db_session, owner_user()), 404)
        await assert_http_error(endpoint(other.id, detection.id, db_session, owner_user()), 404)
        await assert_http_error(endpoint(doc.id, detection.id, db_session, stranger_user()), 403)


async def test_pii_reveal_decrypts_and_writes_audit_log(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-pii-reveal")
    detection = await _pii(db_session, doc, run, original="010-1234-5678")

    result = await st.reveal_pii_detection(doc.id, detection.id, db_session, admin_user())

    assert result == {"value": "010-1234-5678"}
    logs = (await db_session.scalars(select(AuditLog).where(AuditLog.action == "pii.reveal"))).all()
    assert [log.resource_id for log in logs] == [str(detection.id)]


async def test_pii_reveal_requires_admin_and_existing_original(db_session):  # noqa: F811
    doc, run = await doc_with_run(db_session, "s-pii-reveal-g")
    other = await add_doc(db_session, "s-pii-reveal-g2")
    with_secret = await _pii(db_session, doc, run, original="비밀")
    without_secret = await _pii(db_session, doc, run)

    # 문서 소유자(viewer)라도 전역 admin이 아니면 거부 — 문서 존재 확인보다 먼저 막는다
    await assert_http_error(st.reveal_pii_detection(doc.id, with_secret.id, db_session, owner_user()), 403)
    await assert_http_error(st.reveal_pii_detection(uuid4(), with_secret.id, db_session, admin_user()), 404)
    await assert_http_error(st.reveal_pii_detection(doc.id, uuid4(), db_session, admin_user()), 404)
    await assert_http_error(st.reveal_pii_detection(other.id, with_secret.id, db_session, admin_user()), 404)
    err = await assert_http_error(st.reveal_pii_detection(doc.id, without_secret.id, db_session, admin_user()), 404)
    assert "원문" in err.detail


# ------------------------------------------------------------------ jobs
async def test_jobs_listed_oldest_first(db_session):  # noqa: F811
    doc = await add_doc(db_session, "s-jobs")
    now = datetime.utcnow()
    newer = ProcessingJob(id=uuid4(), document_id=doc.id, job_type="embed", status="COMPLETED", created_at=now)
    older = ProcessingJob(id=uuid4(), document_id=doc.id, job_type="parse", status="COMPLETED", created_at=now - timedelta(minutes=1))
    db_session.add_all([newer, older])
    await db_session.flush()

    result = await st.get_document_jobs(doc.id, db_session, owner_user())

    assert [j.job_type for j in result["items"]] == ["parse", "embed"]
    await assert_http_error(st.get_document_jobs(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(st.get_document_jobs(doc.id, db_session, stranger_user()), 403)


# ------------------------------------------------------- content / tables
async def test_content_delegates_to_document_service_after_access_check(db_session):  # noqa: F811
    doc = await add_doc(db_session, "s-content")
    payload = {"document_id": str(doc.id), "chunks": [], "full_text": ""}

    with patch("app.services.document_service.get_document_content", return_value=payload) as fetch:
        assert await st.get_document_content(doc.id, db_session, owner_user()) == payload
        await assert_http_error(st.get_document_content(doc.id, db_session, stranger_user()), 403)
        await assert_http_error(st.get_document_content(uuid4(), db_session, owner_user()), 404)

    fetch.assert_called_once_with(doc.id)


async def test_tables_default_to_empty_list(db_session):  # noqa: F811
    with_tables = await add_doc(db_session, "s-tables", tables=[{"id": "t1", "rows": []}])
    without = await add_doc(db_session, "s-tables-none")

    assert (await st.get_document_tables(with_tables.id, db_session, owner_user()))["tables"] == [{"id": "t1", "rows": []}]
    assert (await st.get_document_tables(without.id, db_session, owner_user()))["tables"] == []
    await assert_http_error(st.get_document_tables(uuid4(), db_session, owner_user()), 404)
    await assert_http_error(st.get_document_tables(without.id, db_session, stranger_user()), 403)
