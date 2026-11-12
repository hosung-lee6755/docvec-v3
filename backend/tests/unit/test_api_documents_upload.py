"""documents/upload.py — 전처리 버전 해석, run 시작, 단건/ZIP 업로드 분기. 실제 Postgres + 가짜 스토리지/Celery."""
import io
import zipfile
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.api.v1.endpoints.documents import upload as up
from app.db.models.collection import Collection
from app.db.models.document import Document
from app.db.models.project import Project
from app.db.models.workflow import WorkflowBlockInstance, WorkflowDefinition, WorkflowEdge, WorkflowVersion
from app.db.models.workflow_run import WorkflowRun
from tests.unit._docs_api_support import OWNER_ID, add_doc, assert_http_error, owner_user, stranger_user
from tests.unit._docs_api_support import db_session  # noqa: F401


# ------------------------------------------------------------------ helpers
async def _workflow(db, kind="PREPROCESS", project_id=None, versions=((1, True),)):
    definition = WorkflowDefinition(id=uuid4(), name=f"wf-{uuid4().hex[:6]}", kind=kind, project_id=project_id, created_by=OWNER_ID)
    db.add(definition)
    await db.flush()
    created = []
    for number, published in versions:
        version = WorkflowVersion(
            id=uuid4(), workflow_id=definition.id, version_number=number, created_by=OWNER_ID,
            published_at=datetime.utcnow() if published else None,
        )
        db.add(version)
        created.append(version)
    await db.flush()
    return definition, created


async def _collection(db, **fields) -> Collection:
    collection = Collection(id=uuid4(), name="c", qdrant_collection_name=f"q_{uuid4().hex[:8]}", created_by=OWNER_ID, **fields)
    db.add(collection)
    await db.flush()
    return collection


class FakeStorage:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.uploaded: list[tuple[str, str, bytes, str]] = []
        self.deleted: list[str] = []

    def upload_file(self, bucket, key, content, content_type):
        if self.fail:
            raise RuntimeError("minio unreachable: secret-host:9000")
        self.uploaded.append((bucket, key, content, content_type))

    def delete_file(self, bucket, key):
        self.deleted.append(key)


@pytest.fixture
def storage(monkeypatch):
    fake = FakeStorage()
    monkeypatch.setattr("app.services.storage.storage_service", fake)
    return fake


@pytest.fixture
def started(monkeypatch):
    """워크플로우 시작을 가짜로 — 호출된 (document_id, version_id, skip_review)를 기록한다."""
    calls: list[tuple] = []

    async def fake(db, document, version_id, skip_review):
        calls.append((str(document.id), version_id, skip_review))

    monkeypatch.setattr(up, "_start_workflow_or_mark_failed", fake)
    return calls


def _file(name: str, content: bytes = b"%PDF-1.4 hello", content_type: str | None = None) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers={"content-type": content_type} if content_type else None)


def _zip(entries: dict[str, bytes]) -> UploadFile:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    buf.seek(0)
    return UploadFile(file=buf, filename="bundle.zip")


# --------------------------------------------- _resolve_preprocess_version_id
async def test_explicit_version_must_be_a_valid_uuid_and_exist(db_session):  # noqa: F811
    await assert_http_error(up._resolve_preprocess_version_id(db_session, None, "not-a-uuid"), 400)
    await assert_http_error(up._resolve_preprocess_version_id(db_session, None, str(uuid4())), 400)


async def test_explicit_version_must_belong_to_a_preprocess_workflow(db_session):  # noqa: F811
    _, [analysis_version] = await _workflow(db_session, kind="ANALYSIS")

    err = await assert_http_error(up._resolve_preprocess_version_id(db_session, None, str(analysis_version.id)), 400)

    assert "PREPROCESS" in err.detail


async def test_explicit_system_version_is_returned_as_is(db_session):  # noqa: F811
    _, [version] = await _workflow(db_session)

    assert await up._resolve_preprocess_version_id(db_session, None, str(version.id)) == version.id


async def test_explicit_project_workflow_requires_project_access(db_session):  # noqa: F811
    project = Project(id=uuid4(), name="p", created_by=OWNER_ID)
    db_session.add(project)
    await db_session.flush()
    _, [version] = await _workflow(db_session, project_id=project.id)

    assert await up._resolve_preprocess_version_id(db_session, None, str(version.id), current_user=owner_user()) == version.id
    await assert_http_error(
        up._resolve_preprocess_version_id(db_session, None, str(version.id), current_user=stranger_user()), 403
    )


async def test_collection_default_workflow_pins_version_number_or_takes_latest_published(db_session):  # noqa: F811
    definition, (v1, v2, v3_draft) = await _workflow(db_session, versions=((1, True), (2, True), (3, False)))
    unpinned = await _collection(db_session, default_workflow_id=definition.id)
    pinned = await _collection(db_session, default_workflow_id=definition.id, default_workflow_version=1)

    assert await up._resolve_preprocess_version_id(db_session, str(unpinned.id)) == v2.id  # 미발행 v3 제외
    assert await up._resolve_preprocess_version_id(db_session, str(pinned.id)) == v1.id


async def test_falls_back_to_system_workflow_latest_published_version(db_session):  # noqa: F811
    _, (_, v2) = await _workflow(db_session, versions=((1, True), (2, True)))
    collection = await _collection(db_session)  # 기본 워크플로우 없음

    assert await up._resolve_preprocess_version_id(db_session, str(collection.id)) == v2.id
    assert await up._resolve_preprocess_version_id(db_session, str(uuid4())) == v2.id  # 모르는 컬렉션도 시스템 기본으로


async def test_missing_system_workflow_or_published_version_is_a_500(db_session):  # noqa: F811
    err = await assert_http_error(up._resolve_preprocess_version_id(db_session, None), 500)
    assert "표준 전처리" in err.detail

    await _workflow(db_session, versions=((1, False),))
    err = await assert_http_error(up._resolve_preprocess_version_id(db_session, None), 500)
    assert "게시된" in err.detail


# ------------------------------------------------ _start_preprocess_workflow
async def test_start_workflow_creates_run_pins_it_and_enqueues_only_entry_blocks(db_session):  # noqa: F811
    definition, [version] = await _workflow(db_session)
    entry = WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type="file_validate", config={"timeoutSeconds": 77})
    gpu = WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type="rag_store", config={})
    db_session.add_all([entry, gpu])
    await db_session.flush()
    db_session.add(WorkflowEdge(id=uuid4(), version_id=version.id, from_block_id=entry.id, to_block_id=gpu.id))
    doc = await add_doc(db_session, "u-start", status="QUEUED")

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as step:
        await up._start_preprocess_workflow(db_session, doc, skip_review=True)

    run = await db_session.scalar(select(WorkflowRun).where(WorkflowRun.document_id == doc.id))
    assert (run.status, run.trigger, run.skip_review, run.version_id) == ("QUEUED", "UPLOAD", True, version.id)
    assert doc.active_run_id == run.id
    step.apply_async.assert_called_once_with(args=[str(run.id), str(entry.id)], time_limit=77, queue="normal")


async def test_start_workflow_defaults_timeout_and_routes_gpu_blocks_to_embed_queue(db_session):  # noqa: F811
    _, [version] = await _workflow(db_session)
    db_session.add(WorkflowBlockInstance(id=uuid4(), version_id=version.id, block_type="rag_store", config={}))
    doc = await add_doc(db_session, "u-start-gpu", status="QUEUED")
    await db_session.flush()

    with patch("app.pipeline.tasks.workflow.run_workflow_step") as step:
        await up._start_preprocess_workflow(db_session, doc, str(version.id))

    kwargs = step.apply_async.call_args.kwargs
    assert (kwargs["time_limit"], kwargs["queue"]) == (1800, "embed")


# ------------------------------------------- _start_workflow_or_mark_failed
@pytest.mark.parametrize(
    "error, expected",
    [(HTTPException(status_code=500, detail="표준 전처리 워크플로우가 없음"), "표준 전처리 워크플로우가 없음"),
     (RuntimeError("redis connection string leaked"), "처리를 시작하지 못했습니다.")],
)
async def test_start_failure_marks_document_failed_with_safe_message_and_reraises(db_session, error, expected):  # noqa: F811
    doc = await add_doc(db_session, f"u-fail-{type(error).__name__}", status="QUEUED")
    await db_session.commit()  # 업로드 핸들러는 이미 커밋된 뒤에 시작을 시도한다
    doc_id = doc.id

    with patch.object(up, "_start_preprocess_workflow", new=AsyncMock(side_effect=error)):
        with pytest.raises(type(error)):
            await up._start_workflow_or_mark_failed(db_session, doc, None, False)

    row = (await db_session.execute(select(Document.status, Document.error_message).where(Document.id == doc_id))).one()
    assert tuple(row) == ("FAILED", expected)


# ------------------------------------------------------------ upload_document
async def test_upload_validates_collection_access_first(db_session, storage, started):  # noqa: F811
    collection = await _collection(db_session)

    await assert_http_error(up.upload_document(_file("a.pdf"), str(uuid4()), False, None, db_session, owner_user()), 404)
    await assert_http_error(up.upload_document(_file("a.pdf"), str(collection.id), False, None, db_session, stranger_user()), 403)
    assert storage.uploaded == [] and started == []


async def test_upload_rejects_unsupported_extension_with_415(db_session, storage, started):  # noqa: F811
    await assert_http_error(up.upload_document(_file("malware.exe"), None, False, None, db_session, owner_user()), 415)
    assert storage.uploaded == []


async def test_upload_stores_original_and_creates_document_in_collection(db_session, storage, started):  # noqa: F811
    collection = await _collection(db_session)
    file = _file("../../etc/보고서.PDF", b"%PDF-1.4 body")

    result = await up.upload_document(file, str(collection.id), True, None, db_session, owner_user())

    assert result["filename"] == "보고서.PDF"  # 경로 성분 제거
    assert result["status"] == "QUEUED"
    [(bucket, key, content, content_type)] = storage.uploaded
    assert key == f"{result['id']}/보고서.PDF" and content == b"%PDF-1.4 body" and content_type == "application/pdf"
    doc = await db_session.get(Document, result["id"])
    assert (str(doc.collection_id), doc.file_size, str(doc.created_by)) == (str(collection.id), len(content), OWNER_ID)
    assert started == [(str(result["id"]), None, True)]


async def test_upload_duplicate_in_same_scope_is_409_but_other_collection_is_allowed(db_session, storage, started):  # noqa: F811
    import hashlib

    content = b"%PDF-1.4 same bytes"
    digest = hashlib.sha256(content).hexdigest()
    collection = await _collection(db_session)
    await add_doc(db_session, "u-dup-1", file_hash=digest)  # 컬렉션 없음
    await add_doc(db_session, "u-dup-2", file_hash=digest, collection_id=collection.id)

    await assert_http_error(up.upload_document(_file("a.pdf", content), None, False, None, db_session, owner_user()), 409)
    await assert_http_error(up.upload_document(_file("a.pdf", content), str(collection.id), False, None, db_session, owner_user()), 409)
    other = await _collection(db_session)
    result = await up.upload_document(_file("a.pdf", content), str(other.id), False, None, db_session, owner_user())
    assert result["status"] == "QUEUED"


async def test_upload_storage_failure_is_500_without_leaking_details_and_leaves_no_row(db_session, monkeypatch, started):  # noqa: F811
    monkeypatch.setattr("app.services.storage.storage_service", FakeStorage(fail=True))
    before = len((await db_session.scalars(select(Document.id))).all())

    err = await assert_http_error(up.upload_document(_file("a.pdf"), None, False, None, db_session, owner_user()), 500)

    assert "secret-host" not in err.detail
    assert len((await db_session.scalars(select(Document.id))).all()) == before
    assert started == []


async def test_upload_commit_failure_releases_orphan_original_and_reraises(db_session, storage, started):  # noqa: F811
    released: list[str] = []

    async def fake_release(db, store, bucket, key):
        released.append(key)

    with (
        patch.object(up, "release_original", new=fake_release),
        patch.object(db_session, "commit", new=AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        with pytest.raises(RuntimeError, match="db down"):
            await up.upload_document(_file("a.pdf"), None, False, None, db_session, owner_user())

    assert released == [storage.uploaded[0][1]]


# ----------------------------------------------------------- upload_documents_zip
async def test_zip_rejects_invalid_archive_and_collection_access(db_session, storage, started):  # noqa: F811
    collection = await _collection(db_session)
    bad = UploadFile(file=io.BytesIO(b"definitely not a zip"), filename="x.zip")

    await assert_http_error(up.upload_documents_zip(bad, None, False, None, db_session, owner_user()), 400)
    await assert_http_error(up.upload_documents_zip(_zip({"a.pdf": b"x"}), str(uuid4()), False, None, db_session, owner_user()), 404)
    await assert_http_error(up.upload_documents_zip(_zip({"a.pdf": b"x"}), str(collection.id), False, None, db_session, stranger_user()), 403)


async def test_zip_total_uncompressed_size_cap(db_session, storage, started, monkeypatch):  # noqa: F811
    monkeypatch.setattr(up, "_ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES", 10)

    err = await assert_http_error(
        up.upload_documents_zip(_zip({"a.pdf": b"x" * 8, "b.pdf": b"y" * 8}), None, False, None, db_session, owner_user()), 400
    )

    assert "총 용량" in err.detail
    assert storage.uploaded == []


async def test_zip_reports_per_entry_outcomes(db_session, storage, started, monkeypatch):  # noqa: F811
    monkeypatch.setattr(up, "_ZIP_MAX_ENTRY_UNCOMPRESSED_BYTES", 20)
    archive = _zip({
        "docs/ok.pdf": b"%PDF ok",
        "notes.txt": b"text",
        "noext": b"data",
        "huge.pdf": b"z" * 21,
        "__MACOSX/._ok.pdf": b"meta",
        ".hidden.pdf": b"hidden",
    })

    result = await up.upload_documents_zip(archive, None, False, None, db_session, owner_user())

    by_name = {r["filename"]: r for r in result["results"]}
    assert result["total_entries"] == 4 and result["queued"] == 1
    assert by_name["ok.pdf"]["status"] == "queued"
    assert by_name["notes.txt"]["status"] == "skipped" and ".txt" in by_name["notes.txt"]["detail"]
    assert "확장자 없음" in by_name["noext"]["detail"]
    assert by_name["huge.pdf"]["status"] == "skipped" and "너무 큽니다" in by_name["huge.pdf"]["detail"]
    assert [call[0] for call in started] == [str(by_name["ok.pdf"]["document_id"])]


async def test_zip_flags_duplicates_inside_collection_scope(db_session, storage, started):  # noqa: F811
    import hashlib

    content = b"%PDF dup"
    collection = await _collection(db_session)
    existing = await add_doc(db_session, "z-dup", file_hash=hashlib.sha256(content).hexdigest(), collection_id=collection.id)

    result = await up.upload_documents_zip(_zip({"a.pdf": content}), str(collection.id), False, None, db_session, owner_user())

    [entry] = result["results"]
    assert entry["status"] == "duplicate" and str(entry["document_id"]) == str(existing.id)
    assert result["queued"] == 0 and storage.uploaded == []


async def test_zip_entry_read_failure_does_not_abort_other_entries(db_session, storage, started):  # noqa: F811
    archive = _zip({"bad.pdf": b"will fail", "good.pdf": b"%PDF good"})
    real_read = zipfile.ZipFile.read

    def flaky_read(self, name, *args, **kwargs):
        if getattr(name, "filename", name) == "bad.pdf":
            raise zipfile.BadZipFile("crc")
        return real_read(self, name, *args, **kwargs)

    with patch.object(zipfile.ZipFile, "read", flaky_read):
        result = await up.upload_documents_zip(archive, None, False, None, db_session, owner_user())

    statuses = {r["filename"]: r["status"] for r in result["results"]}
    assert statuses == {"bad.pdf": "failed", "good.pdf": "queued"}
    assert result["queued"] == 1


async def test_zip_entry_storage_failure_is_reported_without_details(db_session, monkeypatch, started):  # noqa: F811
    monkeypatch.setattr("app.services.storage.storage_service", FakeStorage(fail=True))

    result = await up.upload_documents_zip(_zip({"a.pdf": b"%PDF a"}), None, False, None, db_session, owner_user())

    [entry] = result["results"]
    assert entry == {"filename": "a.pdf", "status": "failed", "detail": "파일 업로드 실패"}
    assert result["queued"] == 0


async def test_zip_commit_failure_releases_original_and_marks_entry_failed(db_session, storage, started):  # noqa: F811
    released: list[str] = []

    async def fake_release(db, store, bucket, key):
        released.append(key)

    with (
        patch.object(up, "release_original", new=fake_release),
        patch.object(db_session, "commit", new=AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        result = await up.upload_documents_zip(_zip({"a.pdf": b"%PDF a"}), None, False, None, db_session, owner_user())

    assert result["results"][0]["status"] == "failed"
    assert released == [storage.uploaded[0][1]]


async def test_same_name_with_new_content_becomes_next_pending_version(db_session, storage, started):  # noqa: F811
    """v3 마일스톤 7: 같은 컬렉션의 같은 파일명이면 새 버전으로 잇고, 처리 전까지는 pending이다."""
    collection = await _collection(db_session)
    first = await up.upload_document(_file("규정.pdf", b"%PDF v1"), str(collection.id), True, None,
                                     db_session, owner_user())

    second = await up.upload_document(_file("규정.pdf", b"%PDF v2"), str(collection.id), True, None,
                                      db_session, owner_user())

    v1, v2 = await db_session.get(Document, first["id"]), await db_session.get(Document, second["id"])
    assert (first["version_number"], second["version_number"]) == (1, 2)
    assert v2.lineage_id == v1.lineage_id == second["lineage_id"]
    assert (v1.lifecycle_state, v2.lifecycle_state) == ("current", "pending")


async def test_new_document_flag_keeps_same_name_as_a_separate_document(db_session, storage, started):  # noqa: F811
    collection = await _collection(db_session)
    first = await up.upload_document(_file("규정.pdf", b"%PDF v1"), str(collection.id), True, None,
                                     db_session, owner_user())

    second = await up.upload_document(_file("규정.pdf", b"%PDF other"), str(collection.id), True, None,
                                      db_session, owner_user(), new_document=True)

    assert second["version_number"] == 1 and second["lineage_id"] != first["lineage_id"]


async def test_new_version_inherits_security_level_and_acl_of_previous_version(db_session, storage, started):  # noqa: F811
    """새 버전이 이전 버전보다 넓게 열리면 승격되는 순간 권한이 풀린다(v3 마일스톤 7)."""
    from app.db.models.document_acl import DocumentAclEntry

    collection = await _collection(db_session)
    first = await up.upload_document(_file("규정.pdf", b"%PDF v1"), str(collection.id), True, None,
                                     db_session, owner_user())
    v1 = await db_session.get(Document, first["id"])
    v1.security_level = "Confidential"
    principal = str(uuid4())
    db_session.add(DocumentAclEntry(document_id=v1.id, principal_type="user", principal_id=principal,
                                    created_by=OWNER_ID))
    await db_session.flush()

    second = await up.upload_document(_file("규정.pdf", b"%PDF v2"), str(collection.id), True, None,
                                      db_session, owner_user())

    v2 = await db_session.get(Document, second["id"])
    inherited = (await db_session.scalars(
        select(DocumentAclEntry.principal_id).where(DocumentAclEntry.document_id == v2.id)
    )).all()
    assert v2.security_level == "Confidential"
    assert [str(p) for p in inherited] == [principal]
