#!/usr/bin/env bash
# DocVec 복원(전체 점검 2-8, 2026-11-16). scripts/backup.sh가 만든 폴더 하나를 통째로 되돌린다.
#
#   scripts/restore.sh <백업 폴더> --yes
#
# 지금 있는 데이터를 지우고 백업 시점으로 바꾼다. 되돌릴 수 없으므로 --yes를 붙여야 실행한다.
# 실행하기 전에 지금 상태를 scripts/backup.sh로 한 번 더 떠 두기를 권한다.
# .env의 ENCRYPTION_KEY는 백업을 뜰 때와 같아야 한다. 다르면 저장된 API 키와 개인정보 원문을 풀 수 없다.
set -euo pipefail

cd "$(dirname "$0")/.."
SRC="${1:-}"
CONFIRM="${2:-}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:16335}"
PG_USER="${POSTGRES_USER:-docvec}"
PG_DB="${POSTGRES_DB:-docvec}"

if [ -z "$SRC" ] || [ ! -f "$SRC/postgres.dump" ] || [ ! -f "$SRC/minio.tar.gz" ] || [ ! -d "$SRC/qdrant" ]; then
  echo "사용법: scripts/restore.sh <백업 폴더> --yes" >&2
  echo "백업 폴더에는 postgres.dump, minio.tar.gz, qdrant/가 있어야 합니다." >&2
  exit 2
fi
if [ "$CONFIRM" != "--yes" ]; then
  echo "지금 데이터를 지우고 '$SRC' 시점으로 되돌립니다. 실행하려면 끝에 --yes를 붙이세요." >&2
  exit 2
fi

echo "[0/3] 데이터를 쓰는 서비스를 멈춥니다"
docker compose stop api worker worker-embed worker-extract beat

echo "[1/3] Postgres"
docker compose exec -T postgres psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$PG_DB\" WITH (FORCE)"
docker compose exec -T postgres psql -U "$PG_USER" -d postgres -c "CREATE DATABASE \"$PG_DB\" OWNER \"$PG_USER\""
docker compose exec -T postgres pg_restore -U "$PG_USER" -d "$PG_DB" --no-owner < "$SRC/postgres.dump"

echo "[2/3] Qdrant"
for file in "$SRC"/qdrant/*.snapshot; do
  name=$(basename "$file" .snapshot)
  curl -fsS -X POST "$QDRANT_URL/collections/$name/snapshots/upload?priority=snapshot" \
    -H "Content-Type: multipart/form-data" -F "snapshot=@$file" > /dev/null
  echo "  $name"
done

echo "[3/3] MinIO"
docker compose stop minio
minio_container=$(docker compose ps -aq minio)
docker run --rm -i --volumes-from "$minio_container" --entrypoint sh postgres:16-alpine \
  -c "find /data -mindepth 1 -delete && tar -xzf - -C /data" < "$SRC/minio.tar.gz"
docker compose start minio

echo "서비스를 다시 올립니다"
docker compose start api worker worker-embed worker-extract beat
echo "끝났습니다. 문서 목록, 검색, 원문 미리보기를 한 번씩 확인하세요."
