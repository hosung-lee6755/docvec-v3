"""v3 마일스톤 3 — 개발용 AD DC(Samba)를 상대로 한 실제 프로토콜 확인(선택 실행).

`docker-compose.dev-directory.yml`의 ad-dc가 떠 있고 DEV_AD_PASSWORD가 주어졌을 때만 돈다.
  DEV_AD_PASSWORD=... pytest tests/unit/test_directory_integration.py
씨앗 데이터는 dev/directory/entrypoint.sh에 있다.
"""
import os
import socket

import pytest

from app.services.connectors.acl_mapping import (
    DECISION_HELD,
    DECISION_OPEN,
    DECISION_RESTRICTED,
    decide_acl,
    parse_security_descriptor,
)
from app.services.connectors.smb_client import SmbSourceClient
from app.services.directory.ldap_client import LdapConfig, LdapDirectoryClient

HOST = os.environ.get("DEV_AD_HOST", "ad-dc")
PASSWORD = os.environ.get("DEV_AD_PASSWORD")


def _reachable() -> bool:
    try:
        with socket.create_connection((HOST, 636), timeout=1):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not PASSWORD or not _reachable(), reason="dev AD DC not available")


@pytest.fixture(scope="module")
def directory():
    return LdapDirectoryClient(LdapConfig(
        url=f"ldaps://{HOST}:636", bind_dn="svc-docvec@docvec.local", bind_password=PASSWORD,
        base_dn="DC=docvec,DC=local", tls_verify=False,
    ))


def test_ldap_login_nested_groups_and_disabled_account(directory):
    alice = directory.authenticate("alice", PASSWORD)
    assert alice is not None and alice.sid.startswith("S-1-5-21-") and alice.email == "alice@docvec.local"
    assert directory.authenticate("alice@docvec.local", PASSWORD).sid == alice.sid
    assert directory.authenticate("alice", "wrong-password") is None
    assert directory.authenticate("dave", PASSWORD) is None  # 비활성
    assert directory.authenticate("alice)(|(sAMAccountName=*", PASSWORD) is None  # 필터 주입
    assert {g.name for g in directory.user_groups(alice.dn)} >= {"sales", "sales-east"}


def test_every_directory_sid_is_well_formed(directory):
    # Builtin 그룹 SID가 깨진 문자열로 들어와 Postgres에 NUL을 넣으려던 회귀를 막는다
    sids = [g.sid for g in directory.list_groups()] + [u.sid for u in directory.list_users()]
    assert sids and all(sid.startswith("S-1-") and "\x00" not in sid for sid in sids)


def test_plain_ldap_is_refused_without_explicit_dev_flag():
    with pytest.raises(ValueError):
        LdapDirectoryClient(LdapConfig(url=f"ldap://{HOST}:389", bind_dn="x", bind_password="y", base_dn="z"))


def test_smb_files_map_to_expected_decisions(directory):
    users = {u.sid: u.username for u in directory.list_users()}
    groups = {g.sid: g.name for g in directory.list_groups()}
    svc_sid = next(sid for sid, name in users.items() if name == "svc-docvec")
    # 도메인 Administrator는 v3 사용자가 아니라고 가정한다(실제 운영과 같게)
    sid_to_user = {sid: name for sid, name in users.items() if name in ("alice", "bob", "carol")}

    client = SmbSourceClient(HOST, "docs", "svc-docvec@docvec.local", PASSWORD)
    try:
        files = {f.path: f for f in client.list_files()}
        assert {"sales/plan.txt", "public/notice.txt", "held/denied.txt"} <= set(files)
        assert "2027".encode() in client.read_file("sales/plan.txt", 1024 * 1024)

        def decide(path):
            aces = parse_security_descriptor(client.read_security_descriptor(path))
            return decide_acl(aces, sid_to_user=sid_to_user, sid_to_group=groups, ignored_sids={svc_sid})

        assert decide("public/notice.txt").kind == DECISION_OPEN
        sales = decide("sales/plan.txt")
        assert (sales.kind, set(sales.groups)) == (DECISION_RESTRICTED, {"sales"})
        alice = decide("personal/alice.txt")
        assert (alice.kind, set(alice.users)) == (DECISION_RESTRICTED, {"alice"})
        assert decide("held/denied.txt").reason == "deny_ace"
        assert decide("held/unmapped.txt").kind == DECISION_HELD
    finally:
        client.close()
