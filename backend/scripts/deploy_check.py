"""배포 전후 점검 — 마이그레이션, 관리자 가입 코드, 로컬 폴더 루트, AD 설정, 암호화 키를 확인한다.

사용(컨테이너 안):
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.deploy_check"
실패(fail)가 있으면 종료 코드 1이다.
"""
from app.db.session import get_sync_db
from app.services.deploy_check import FAIL, run_checks

_MARK = {"ok": "[OK]  ", "warn": "[주의]", "fail": "[실패]"}


def main() -> int:
    db = get_sync_db()
    try:
        checks = run_checks(db)
    finally:
        db.close()
    for check in checks:
        print(f"{_MARK[check.level]} {check.name}: {check.message}")
    return 1 if any(c.level == FAIL for c in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
