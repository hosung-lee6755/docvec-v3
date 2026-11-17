"""키워드 색인 백필 — 기존 청크 점으로 키워드 전용 컬렉션(<청크 컬렉션>_lex)을 채운다.

하이브리드 검색은 키워드 색인에서 찾은 후보를 벡터 후보에 더한다(services/lexical_index.py).
이 색인이 생기기 전에 저장한 문서는 한 번 채워야 키워드로 찾을 수 있다. 재임베딩하지 않고
본문만 다시 토큰으로 나눈다. 불용어·동의어 사전을 크게 바꾼 뒤에도 다시 돌린다.
여러 번 실행해도 안전하다(같은 점 id에 덮어쓴다).

사용(컨테이너 안):
    docker compose exec api sh -c "cd /app && .venv/bin/python -m scripts.backfill_lexical_index"
"""
import argparse
import logging
import sys

from app.core.config import settings
from app.db.session import get_sync_db
from app.services.dictionary_service import ensure_dictionary_cache_sync
from app.services.qdrant_service import qdrant_service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--batch-size", type=int, default=200)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    db = get_sync_db()
    try:
        ensure_dictionary_cache_sync(db)
    finally:
        db.close()

    stats = qdrant_service.rebuild_lexical(settings.qdrant_collection_name, batch_size=args.batch_size)
    logging.info("scanned=%d indexed=%d", stats["scanned"], stats["indexed"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
