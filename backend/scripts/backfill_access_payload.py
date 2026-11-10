"""v3 권한 사본 백필 — 기존 Qdrant 포인트(본문 청크·문서 요약)에 sec_rank/acl/owner_id/
collection_id를 채우고 권한 필드 인덱스를 만든다. 재임베딩하지 않는다.

v3 검색 필터는 권한 필드가 없는 포인트를 매칭하지 않으므로(fail-closed), v2 데이터로
배포한 직후 이 스크립트를 한 번 돌리기 전까지 기존 문서는 검색·채팅에 나오지 않는다.
여러 번 실행해도 안전하다(멱등).

사용(컨테이너 안):
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.backfill_access_payload --dry-run"
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.backfill_access_payload"
"""
import argparse
import logging
import sys

from app.db.session import get_sync_db
from app.services.access_payload import backfill_access_payloads


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="대상 수만 확인하고 변경하지 않는다")
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = get_sync_db()
    try:
        stats = backfill_access_payloads(db, dry_run=args.dry_run, batch_size=args.batch_size)
    finally:
        db.close()

    mode = "DRY-RUN" if args.dry_run else "APPLIED"
    logging.info(
        "[%s] collections=%s documents=%d synced=%d failed=%d",
        mode, stats["collections"], stats["documents"], stats["synced"], len(stats["failed"]),
    )
    for doc_id in stats["failed"]:
        logging.error("sync failed: document=%s (다시 실행하면 재시도된다)", doc_id)
    return 1 if stats["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
