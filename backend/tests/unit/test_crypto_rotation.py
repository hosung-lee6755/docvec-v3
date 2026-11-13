"""암호화 키 교체 — 예전 키로 쓴 값을 계속 읽고, 스크립트로 현재 키로 다시 암호화한다."""
from types import SimpleNamespace

import pytest
from cryptography.fernet import InvalidToken

from app.core import crypto
from app.core.config import settings
from app.services import key_rotation


@pytest.fixture
def keys(monkeypatch):
    def use(current: str, previous: str = ""):
        monkeypatch.setattr(settings, "encryption_key", current)
        monkeypatch.setattr(settings, "encryption_keys_previous", previous)
    return use


def test_values_written_with_the_old_key_stay_readable_after_rotation(keys):
    keys("old-key")
    old_cipher = crypto.encrypt_secret("sk-secret")

    keys("new-key", "old-key")

    assert crypto.decrypt_secret(old_cipher) == "sk-secret"
    assert crypto.is_current_key(old_cipher) is False
    rotated = crypto.rotate_secret(old_cipher)
    assert crypto.is_current_key(rotated) is True

    keys("new-key")  # 예전 키를 빼도 다시 암호화한 값은 읽힌다
    assert crypto.decrypt_secret(rotated) == "sk-secret"
    with pytest.raises(InvalidToken):
        crypto.decrypt_secret(old_cipher)


def test_new_values_always_use_the_current_key(keys):
    keys("new-key", "old-key, other-old")
    cipher = crypto.encrypt_secret("value")
    keys("new-key")
    assert crypto.decrypt_secret(cipher) == "value"


def test_a_previous_entry_equal_to_the_current_key_is_ignored(keys):
    keys("same", "same")
    assert crypto._previous_key_materials() == []


class _FakeDb:
    """rotate_all이 쓰는 scalars/commit만 흉내 낸다. 모델마다 한 번만 행을 돌려준다."""

    def __init__(self, rows_by_model):
        self.rows_by_model = rows_by_model
        self.served = set()
        self.commits = 0

    def scalars(self, stmt):
        model = stmt.column_descriptions[0]["entity"]
        rows = [] if model in self.served else self.rows_by_model.get(model, [])
        self.served.add(model)
        return SimpleNamespace(all=lambda: rows)

    def commit(self):
        self.commits += 1


def _row(value, row_id):
    return SimpleNamespace(id=row_id, encrypted_key=value)


def test_rotate_all_reencrypts_old_values_and_reports_unreadable_ones(keys):
    keys("old-key")
    old = crypto.encrypt_secret("a")
    keys("new-key", "old-key")
    current = crypto.encrypt_secret("b")
    keys("lost-key")
    lost = crypto.encrypt_secret("c")
    keys("new-key", "old-key")

    rows = [_row(old, 1), _row(current, 2), _row(lost, 3)]

    dry = key_rotation.rotate_all(_FakeDb({key_rotation.UserApiKey: rows}), dry_run=True)
    stats = dry["user_api_keys.encrypted_key"]
    assert (stats.checked, stats.current, stats.rotated, stats.unreadable) == (3, 1, 1, ["3"])
    assert rows[0].encrypted_key == old  # dry-run은 바꾸지 않는다

    db = _FakeDb({key_rotation.UserApiKey: rows})
    applied = key_rotation.rotate_all(db, dry_run=False)["user_api_keys.encrypted_key"]
    assert applied.rotated == 1 and db.commits == 1
    assert crypto.is_current_key(rows[0].encrypted_key)
    assert crypto.decrypt_secret(rows[0].encrypted_key) == "a"
