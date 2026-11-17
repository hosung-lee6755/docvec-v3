"""보안등급별 외부 모델 차단(전체 점검 2-11)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.services import external_model_policy as policy


def _db(rows):
    db = MagicMock()
    db.query.return_value.outerjoin.return_value.filter.return_value.all.return_value = rows
    return db


def test_default_limit_sends_internal_but_not_confidential(monkeypatch):
    monkeypatch.setattr(settings, "external_model_max_security_level", "Internal")

    assert policy.allows_external("Public") and policy.allows_external("Internal")
    assert not policy.allows_external("Confidential")
    # 문서에 등급이 없으면 컬렉션 기본 등급을 따른다
    assert policy.allows_external(None, "Public") and not policy.allows_external(None, "Confidential")
    assert not policy.allows_external("처음 보는 등급")


def test_invalid_setting_blocks_everything(monkeypatch):
    monkeypatch.setattr(settings, "external_model_max_security_level", "oops")

    assert not policy.allows_external("Public")


def test_blocked_ids_include_high_level_and_missing_documents(monkeypatch):
    monkeypatch.setattr(settings, "external_model_max_security_level", "Internal")
    a, b, c, gone = (f"00000000-0000-0000-0000-00000000000{n}" for n in range(1, 5))
    db = _db([(a, "Internal", None), (b, None, "Confidential"), (c, "Confidential", "Public")])

    assert policy.blocked_document_ids(db, [a, b, c, gone, None, "not-an-id"]) == sorted([b, c, gone, "not-an-id"])
    assert policy.blocked_document_ids(db, [None]) == []
    # id 모양이 아닌 값만 있으면 조회하지 않고 막는다
    untouched = MagicMock()
    assert policy.blocked_document_ids(untouched, ["d1"]) == ["d1"]
    untouched.query.assert_not_called()


def test_ensure_raises_a_message_the_user_can_act_on(monkeypatch):
    monkeypatch.setattr(settings, "external_model_max_security_level", "Internal")

    doc = "00000000-0000-0000-0000-000000000001"
    policy.ensure_external_allowed(_db([(doc, "Public", None)]), [{"document_id": doc}])
    with pytest.raises(policy.ExternalModelBlockedError, match="로컬 모델"):
        policy.ensure_external_allowed(_db([(doc, "Confidential", None)]), [{"document_id": doc}])


def test_document_check_uses_the_collection_default(monkeypatch):
    monkeypatch.setattr(settings, "external_model_max_security_level", "Internal")
    db = MagicMock()
    db.get.return_value = SimpleNamespace(default_security_level="Confidential")

    assert not policy.document_allows_external(db, SimpleNamespace(collection_id="c", security_level=None))
    assert policy.document_allows_external(db, SimpleNamespace(collection_id="c", security_level="Public"))
    assert policy.document_allows_external(db, SimpleNamespace(collection_id=None, security_level=None))


def test_backend_kinds():
    assert policy.is_external_backend("openai") and policy.is_external_backend("anthropic")
    assert not policy.is_external_backend("local") and not policy.is_external_backend(None)
