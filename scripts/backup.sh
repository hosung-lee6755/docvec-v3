#!/usr/bin/env bash
# DocVec 백업(전체 점검 2-8, 2026-11-16). 세 저장소를 같은 시점에 함께 뜬다.
#
#   scripts/backup.sh [저장할 폴더]      기본값: backups/<날짜_시각>
#
# 만드는 것
#   postgres.dump         pg_dump 커스텀 형식(문서, 청크, 권한, 감사 기록)
#   qdrant/<이름>.snapshot Qdrant 컬렉션 스냅샷(벡터와 키워드 색인)
#   minio.tar.gz          MinIO 데이터 볼륨(원본 파일과 미리보기)
#   manifest.txt          뜬 시각, 컬렉션 목록, 파일 크기
#
# 세 저장소는 문서 id, 저장 키, 점 id로 서로 묶여 있다. 따로 뜬 것을 섞어 복원하면 검색 결과와
# 원본이 어긋난다. 처리 중인 문서가 없을 때 돌린다. 백업에는 .env가 들어가지 않는다. ENCRYPTION_KEY를
# 잃으면 저장된 API 키와 개인정보 원문을 풀 수 없으므로 .env는 따로 안전하게 보관한다.
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="${1:-backups/$(date +%Y%m%d_%H%M%S)}"
QDRANT_URL="${QDRANT_URL:-http://127.0.0.1:16335}"
PG_USER="${POSTGRES_USER:-docvec}"
PG_DB="${POSTGRES_DB:-docvec}"

mkdir -p "$OUT/qdrant"
echo "백업 위치: $OUT"

running=$(docker compose exec -T postgres psql -U "$PG_USER" -d "$PG_DB" -Atc \
  "select count(*) from workflow_runs where status in ('RUNNING','QUEUED')")
if [ "$running" != "0" ]; then
  echo "경고: 처리 중인 워크플로우 실행이 ${running}건 있습니다. 끝난 뒤에 뜨는 것이 안전합니다." >&2
fi

echo "[1/3] Postgres"
docker compose exec -T postgres pg_dump -U "$PG_USER" -Fc "$PG_DB" > "$OUT/postgres.dump"

echo "[2/3] Qdrant"
collections=$(curl -fsS "$QDRANT_URL/collections" | grep -o '"name":"[^"]*"' | cut -d'"' -f4)
for name in $collections; do
  snapshot=$(curl -fsS -X POST "$QDRANT_URL/collections/$name/snapshots" | grep -o '"name":"[^"]*"' | head -1 | cut -d'"' -f4)
  curl -fsS "$QDRANT_URL/collections/$name/snapshots/$snapshot" -o "$OUT/qdrant/$name.snapshot"
  # 서버에 남은 스냅샷은 지운다. 두면 Qdrant 볼륨이 백업할 때마다 커진다
  curl -fsS -X DELETE "$QDRANT_URL/collections/$name/snapshots/$snapshot" > /dev/null
  echo "  $name"
done

echo "[3/3] MinIO"
minio_container=$(docker compose ps -q minio)
# 이미 받아 둔 postgres 이미지를 tar 실행용으로 쓴다(새 이미지를 내려받지 않는다)
docker run --rm --volumes-from "$minio_container" --entrypoint tar postgres:16-alpine -czf - -C /data . > "$OUT/minio.tar.gz"

{
  echo "created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "qdrant_collections=$(echo $collections | tr ' ' ',')"
  echo "running_workflows_at_backup=$running"
  ls -l "$OUT" "$OUT/qdrant" | awk 'NF>=9 {print $5, $9}'
} > "$OUT/manifest.txt"

echo "끝났습니다."
cat "$OUT/manifest.txt"
