"""pii_blocks: 정규식/체크섬 탐지와 마스킹 액션 테스트 (DB·암호화 경계는 모킹)."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.blocks import pii_blocks as pb
from app.pipeline.blocks.base import BlockContext


def _valid_rrn(front="900101", back_head="123456"):
    digits = front + back_head
    total = sum(int(d) * w for d, w in zip(digits, pb._RRN_WEIGHTS))
    return front + "-" + back_head + str((11 - total % 11) % 10)


VALID_RRN = _valid_rrn()
VALID_CARD = "4111-1111-1111-1111"


def _ctx(text, config=None, extra=None, document_id="doc-1"):
    return BlockContext(
        run_id="r1", block_instance_id="b1", document_id=document_id,
        upstream_outputs={"up": {"text": text, **(extra or {})}}, config=config or {},
    )


def _run(text, config=None, entries=None, extra=None):
    db = MagicMock()
    db.get.return_value = SimpleNamespace(dictionary_version=3)
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.core.crypto.encrypt_secret", side_effect=lambda s: f"enc({s})"), \
            patch.object(pb, "_dictionary_version_cutoff", return_value=None), \
            patch.object(pb, "_load_entries_as_of", return_value=entries or []):
        result = pb.PiiDetectBlock().run(_ctx(text, config, extra))
    return result, db


def _added(db):
    return [c.args[0] for c in db.add.call_args_list]


# ---- 체크섬 ----
def test_rrn_checksum_accepts_valid_and_rejects_wrong_check_digit():
    digits = VALID_RRN.replace("-", "")
    assert pb._rrn_checksum_valid(digits) is True
    wrong = digits[:-1] + str((int(digits[-1]) + 1) % 10)
    assert pb._rrn_checksum_valid(wrong) is False


@pytest.mark.parametrize("value", ["", "123", "12345678901ab", "1" * 14])
def test_rrn_checksum_rejects_bad_shape(value):
    assert pb._rrn_checksum_valid(value) is False


def test_luhn_valid_and_invalid():
    assert pb._luhn_valid("4111111111111111") is True
    assert pb._luhn_valid("4111111111111112") is False
    assert pb._luhn_valid("41a1") is False


# ---- 정규식 탐지기 ----
def test_detect_rrn_only_with_valid_checksum():
    text = f"주민번호 {VALID_RRN} 그리고 900101-1234560"
    matches = pb._detect_regex_matches(text, "RRN")
    assert len(matches) in (1, 2)
    assert all(m[2] == 0.95 for m in matches)
    assert text[matches[0][0]:matches[0][1]] == VALID_RRN


def test_detect_card_requires_luhn():
    text = f"카드 {VALID_CARD} / 1234-5678-9012-3456"
    matches = pb._detect_regex_matches(text, "CARD")
    assert [text[s:e] for s, e, _ in matches] == [VALID_CARD]


def test_detect_phone_formats():
    text = "010-1234-5678, 01012345678, 02-123-4567 은 아님 031-123-4567"
    found = [text[s:e] for s, e, _ in pb._detect_regex_matches(text, "PHONE")]
    assert "010-1234-5678" in found and "01012345678" in found and "031-123-4567" in found


def test_detect_email_and_account_confidence():
    text = "문의 user.name+tag@example.co.kr 계좌 110-123-456789"
    email = pb._detect_regex_matches(text, "EMAIL")
    account = pb._detect_regex_matches(text, "ACCOUNT")
    assert email[0][2] == 0.98 and text[email[0][0]:email[0][1]] == "user.name+tag@example.co.kr"
    assert account[0][2] == 0.5


def test_detect_unknown_type_returns_empty():
    assert pb._detect_regex_matches("아무 텍스트", "NAME") == []
    assert pb._detect_regex_matches("", "EMAIL") == []


# ---- 블록 run ----
def test_run_requires_document_id():
    ctx = _ctx("텍스트", document_id=None)
    with pytest.raises(ValueError):
        pb.PiiDetectBlock().run(ctx)


def test_run_masks_by_default_with_mask_char():
    result, db = _run("메일 a@b.com 입니다")
    assert result.output["text"] == "메일 " + "*" * 7 + " 입니다"
    assert result.metrics == {"pii_detections": 1}
    assert result.requires_review is False
    row = _added(db)[0]
    assert row.entity_type == "EMAIL" and row.action == "MASK"
    assert row.original_encrypted == "enc(a@b.com)"
    db.commit.assert_called_once()
    db.close.assert_called_once()


def test_run_custom_mask_char():
    result, _ = _run("a@b.com", {"mask_char": "#"})
    assert result.output["text"] == "#######"


def test_run_tokenize_action():
    result, db = _run(f"RRN {VALID_RRN} 끝", {"action": "tokenize"})
    assert result.output["text"] == "RRN [MASK:RRN] 끝"
    assert _added(db)[0].action == "TOKENIZE"


def test_run_remove_action():
    result, db = _run("전화 010-1234-5678 끝", {"action": "remove"})
    assert result.output["text"] == "전화  끝"
    assert _added(db)[0].masked_value == ""


def test_run_mark_only_leaves_text_untouched():
    text = "a@b.com"
    result, db = _run(text, {"action": "mark_only"})
    assert result.output["text"] == text
    assert _added(db)[0].masked_value is None
    assert _added(db)[0].action == "MARK"


def test_run_exclude_from_embedding_collects_spans_and_merges_upstream():
    result, db = _run(
        "a@b.com", {"action": "exclude_from_embedding"},
        extra={"pii_excluded_spans": [[100, 110]]},
    )
    assert result.output["text"] == "a@b.com"
    assert result.output["pii_excluded_spans"] == [[100, 110], [0, 7]]
    assert _added(db)[0].action == "EXCLUDE_EMBEDDING"


def test_run_entity_types_filter():
    result, _ = _run("a@b.com 010-1234-5678", {"entity_types": ["EMAIL"], "action": "tokenize"})
    assert result.output["text"] == "[MASK:EMAIL] 010-1234-5678"


def test_run_card_wins_over_overlapping_account_pattern():
    result, db = _run(f"카드 {VALID_CARD}", {"action": "tokenize"})
    types = [r.entity_type for r in _added(db)]
    assert types == ["CARD"]
    assert "[MASK:CARD]" in result.output["text"]


def test_run_multiple_detections_replaced_from_the_back():
    result, _ = _run("a@b.com 와 c@d.com", {"action": "tokenize"})
    assert result.output["text"] == "[MASK:EMAIL] 와 [MASK:EMAIL]"
    assert result.metrics["pii_detections"] == 2


def test_run_require_admin_approval_flags_review_only_when_found():
    found, _ = _run("a@b.com", {"require_admin_approval": True})
    none, _ = _run("깨끗한 문장", {"require_admin_approval": True})
    assert found.requires_review is True
    assert none.requires_review is False
    assert none.metrics["pii_detections"] == 0


def test_run_name_detection_uses_person_entries_and_variants():
    person = SimpleNamespace(
        term="김민준", term_type="PERSON", case_sensitive=True,
        variants=[SimpleNamespace(variant_term="민준씨")],
    )
    other = SimpleNamespace(term="에너지", term_type="TERM", case_sensitive=True, variants=[])
    result, db = _run(
        "김민준 님과 민준씨 그리고 에너지", {"entity_types": ["NAME"], "action": "tokenize"},
        entries=[person, other],
    )
    assert result.output["text"] == "[MASK:NAME] 님과 [MASK:NAME] 그리고 에너지"
    assert all(r.confidence == 0.6 for r in _added(db))


def test_run_missing_workflow_run_still_works():
    db = MagicMock()
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.core.crypto.encrypt_secret", return_value="x"), \
            patch.object(pb, "_dictionary_version_cutoff", return_value=None) as cutoff, \
            patch.object(pb, "_load_entries_as_of", return_value=[]):
        pb.PiiDetectBlock().run(_ctx("텍스트", {"entity_types": ["NAME"]}))
    cutoff.assert_called_once_with(db, None)


def test_run_carries_upstream_keys():
    result, _ = _run("텍스트", extra={"category": "보고서"})
    assert result.output["category"] == "보고서"


def test_run_closes_db_when_commit_fails():
    db = MagicMock()
    db.commit.side_effect = RuntimeError("boom")
    db.get.return_value = None
    with patch("app.db.session.get_sync_db", return_value=db), \
            patch("app.core.crypto.encrypt_secret", return_value="x"):
        with pytest.raises(RuntimeError):
            pb.PiiDetectBlock().run(_ctx("a@b.com"))
    db.close.assert_called_once()


def test_invalid_action_raises_key_error():
    with patch("app.db.session.get_sync_db", return_value=MagicMock()), \
            patch("app.core.crypto.encrypt_secret", return_value="x"):
        with pytest.raises(KeyError):
            pb.PiiDetectBlock().run(_ctx("텍스트", {"action": "nope"}))


def test_block_metadata():
    block = pb.PiiDetectBlock()
    assert block.block_type == "pii_detect"
    assert block.category == "구조·보호"
    assert block.config_schema is pb.PiiDetectConfig
