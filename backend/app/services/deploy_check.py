"""배포 전후 점검 — 유지보수 가이드의 배포 순서에서 빠뜨리기 쉬운 것을 확인한다.

각 항목은 (단계, 메시지)이고 단계는 ok/warn/fail이다. fail이 하나라도 있으면 배포를 멈춘다.
DB 연결은 sync 세션을 받는다(scripts/deploy_check.py).
"""
import os
from dataclasses import dataclass

from sqlalchemy import select, text

from app.core.config import settings
from app.db.models.user import User

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass(frozen=True)
class Check:
    level: str
    name: str
    message: str


def _alembic_head() -> str | None:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def check_migration(db, head: str | None = None) -> Check:
    head = head or _alembic_head()
    current = db.execute(text("select version_num from alembic_version")).scalar_one_or_none()
    if current != head:
        return Check(FAIL, "마이그레이션", f"DB 리비전 {current}이(가) 최신 {head}이(가) 아닙니다. alembic upgrade head를 실행하세요.")
    return Check(OK, "마이그레이션", f"최신 리비전 {head}")


def check_admin_code(db) -> Check:
    if not settings.admin_signup_code:
        return Check(OK, "관리자 가입 코드", "비어 있음")
    has_admin = db.execute(
        select(User.id).where(User.role == "admin", User.is_active.is_(True)).limit(1)
    ).scalar_one_or_none() is not None
    if has_admin:
        return Check(WARN, "관리자 가입 코드",
                     "활성 관리자가 있어 코드로는 더 가입할 수 없지만, ADMIN_SIGNUP_CODE를 비워 두는 편이 안전합니다.")
    return Check(OK, "관리자 가입 코드", "첫 관리자 가입 대기 중. 가입한 뒤 비우세요.")


def check_local_root() -> Check:
    root = settings.connector_local_root
    if not os.path.isdir(root):
        return Check(WARN, "로컬 폴더 루트",
                     f"{root}이(가) 없습니다. 서버 로컬 폴더 연결을 쓰려면 CONNECTOR_LOCAL_DIR를 붙이고 api·worker를 다시 만드세요.")
    folders = [e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")]
    return Check(OK, "로컬 폴더 루트", f"{root} 하위 폴더 {len(folders)}개")


def check_directory() -> list[Check]:
    if not settings.ldap_enabled:
        return [Check(OK, "AD 연결", "꺼져 있음(로컬 계정 모드)")]
    checks = []
    if not settings.ldap_base_dn:
        checks.append(Check(FAIL, "AD 연결", "LDAP_BASE_DN이 비어 있습니다."))
    if settings.ldap_ca_cert_file and not os.path.isfile(settings.ldap_ca_cert_file):
        checks.append(Check(FAIL, "AD 연결", f"LDAP_CA_CERT_FILE {settings.ldap_ca_cert_file}이(가) 없습니다."))
    if not settings.ldap_admin_group_dn:
        checks.append(Check(WARN, "AD 연결", "LDAP_ADMIN_GROUP_DN이 비어 있어 AD로 관리자를 정하지 않습니다."))
    if settings.ldap_preprovision_users:
        checks.append(Check(OK, "AD 사전 등록",
                            "켜짐. 시스템·서비스 계정은 빠집니다. 더 뺄 계정은 LDAP_PREPROVISION_EXCLUDE에 넣습니다."))
    return checks or [Check(OK, "AD 연결", "설정 확인")]


def check_encryption() -> list[Check]:
    checks = []
    if not settings.encryption_key:
        checks.append(Check(WARN, "암호화 키", "ENCRYPTION_KEY가 비어 SECRET_KEY로 암호화합니다(운영에서는 기동을 거부)."))
    if settings.encryption_keys_previous:
        checks.append(Check(WARN, "암호화 키",
                            "ENCRYPTION_KEYS_PREVIOUS가 남아 있습니다. scripts.rotate_encryption_key를 돌린 뒤 비우세요."))
    return checks or [Check(OK, "암호화 키", "현재 키 하나만 사용")]


def run_checks(db) -> list[Check]:
    checks = [check_migration(db), check_admin_code(db), check_local_root()]
    checks += check_directory()
    checks += check_encryption()
    return checks
