"""암호화 키 교체 — 저장된 암호문(외부 API 키, 파일 서버 비밀번호, 개인정보 원문)을 현재 ENCRYPTION_KEY로
다시 암호화한다. 예전 키는 ENCRYPTION_KEYS_PREVIOUS에 있어야 읽을 수 있다. 여러 번 실행해도 안전하다.

사용(컨테이너 안):
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.rotate_encryption_key --dry-run"
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.rotate_encryption_key"
"""
import argparse
import logging

from app.db.session import get_sync_db
from app.services.key_rotation import rotate_all


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="대상 수만 확인하고 변경하지 않는다")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = get_sync_db()
    try:
        report = rotate_all(db, dry_run=args.dry_run)
    finally:
        db.close()

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    unreadable = 0
    for name, stats in report.items():
        logging.info("[%s] %s %s", mode, name, stats.as_dict())
        for row_id in stats.unreadable:
            logging.error("어떤 키로도 풀리지 않음: %s id=%s (ENCRYPTION_KEYS_PREVIOUS를 확인)", name, row_id)
        unreadable += len(stats.unreadable)
    return 1 if unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
