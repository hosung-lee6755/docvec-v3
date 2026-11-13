"""배포 점검 스크립트의 판정."""
from types import SimpleNamespace

from app.core.config import settings
from app.services import deploy_check as dc


class _Db:
    """execute()가 넘겨받은 값을 차례로 돌려준다."""

    def __init__(self, *answers):
        self.answers = list(answers)

    def execute(self, _stmt):
        value = self.answers.pop(0) if self.answers else None
        return SimpleNamespace(scalar_one_or_none=lambda: value)


def test_migration_behind_head_fails():
    assert dc.check_migration(_Db("old"), head="new").level == dc.FAIL
    assert dc.check_migration(_Db("new"), head="new").level == dc.OK


def test_admin_code_left_after_an_admin_exists_is_a_warning(monkeypatch):
    monkeypatch.setattr(settings, "admin_signup_code", "code")
    assert dc.check_admin_code(_Db("admin-id")).level == dc.WARN
    assert dc.check_admin_code(_Db(None)).level == dc.OK
    monkeypatch.setattr(settings, "admin_signup_code", "")
    assert dc.check_admin_code(_Db()).level == dc.OK


def test_missing_local_root_is_a_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "connector_local_root", str(tmp_path / "none"))
    assert dc.check_local_root().level == dc.WARN
    (tmp_path / "a").mkdir()
    monkeypatch.setattr(settings, "connector_local_root", str(tmp_path))
    check = dc.check_local_root()
    assert check.level == dc.OK and "1개" in check.message


def test_directory_settings(monkeypatch):
    monkeypatch.setattr(settings, "ldap_enabled", True)
    monkeypatch.setattr(settings, "ldap_base_dn", "")
    monkeypatch.setattr(settings, "ldap_ca_cert_file", "/no/such/ca.pem")
    assert dc.FAIL in {c.level for c in dc.check_directory()}
    monkeypatch.setattr(settings, "ldap_enabled", False)
    assert [c.level for c in dc.check_directory()] == [dc.OK]


def test_leftover_previous_keys_are_flagged(monkeypatch):
    monkeypatch.setattr(settings, "encryption_key", "k")
    monkeypatch.setattr(settings, "encryption_keys_previous", "old")
    assert any("ENCRYPTION_KEYS_PREVIOUS" in c.message for c in dc.check_encryption())
    monkeypatch.setattr(settings, "encryption_keys_previous", "")
    assert [c.level for c in dc.check_encryption()] == [dc.OK]
