# config_schema.md
# Document Vectorization Platform - Runtime Configuration

## 1. 문서 목적

본 문서는 실제 애플리케이션 런타임 설정 스키마를 정의한다.
`core/config.py`의 `Settings` 클래스로 구현되며, 환경변수로 오버라이드 가능하다.

---

## 2. 런타임 Settings (core/config.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 앱
    app_name: str = "DocVec Platform"
    environment: str = "development"  # development | staging | production | test
    debug: bool = False
    
    # 데이터베이스
    database_url: str = "postgresql+asyncpg://..."
    
    # Redis (캐싱, Celery 브로커)
    redis_url: str = "redis://localhost:6379"
    
    # Qdrant (벡터 DB)
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection_name: str = "documents"  # 모든 컬렉션이 공유하는 단일 물리적 컬렉션
    
    # MinIO (문서 원본 및 아티팩트 저장소)
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minio_secret"
    minio_bucket_originals: str = "originals"    # 업로드된 원본 문서
    minio_bucket_artifacts: str = "artifacts"    # 렌더링된 PDF, 썸네일 등
    
    # Celery (백그라운드 작업)
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    
    # 파이프라인 기본값
    default_chunk_max_tokens: int = 512
    default_chunk_min_tokens: int = 50
    default_chunk_overlap_tokens: int = 64
    default_embedding_model: str = "bge-m3"
    default_embedding_dimension: int = 1024      # 고정 차원 (모든 컬렉션이 공유)
    
    # API 키 (선택)
    openai_api_key: str = ""
```

---

## 3. 환경변수 오버라이드

`.env` 파일 또는 시스템 환경변수로 설정 가능 (환경변수명은 대문자):

```bash
ENVIRONMENT=production
QDRANT_HOST=qdrant.example.com
MINIO_ENDPOINT=minio.example.com
DEFAULT_EMBEDDING_MODEL=openai-text-embedding-3-small
OPENAI_API_KEY=sk-...
```

---

## 4. ProcessingOptions 루트 스키마 (레거시)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PipelineMode(str, Enum):
    FULL_AUTO = "FULL_AUTO"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    AUTO_WITH_LOW_CONFIDENCE = "AUTO_WITH_LOW_CONFIDENCE"


@dataclass
class ProcessingOptions:
    pipeline_mode: PipelineMode = PipelineMode.FULL_AUTO
    ocr: "OcrOptions" = field(default_factory=lambda: OcrOptions())
    chunking: "ChunkingOptions" = field(default_factory=lambda: ChunkingOptions())
    embedding: "EmbeddingOptions" = field(default_factory=lambda: EmbeddingOptions())
    quality: "QualityOptions" = field(default_factory=lambda: QualityOptions())
    export: "ExportOptions" = field(default_factory=lambda: ExportOptions())
    language: "LanguageOptions" = field(default_factory=lambda: LanguageOptions())
```

---

## 3. OcrOptions

```python
class OcrEngine(str, Enum):
    TESSERACT = "tesseract"
    CLOVA = "clova"
    DISABLED = "disabled"


@dataclass
class OcrOptions:
    engine: OcrEngine = OcrEngine.TESSERACT

    # 트리거 임계값
    native_text_coverage_threshold: float = 0.3   # 이하 시 페이지 전체 OCR
    image_area_ratio_threshold: float = 0.5        # 초과 시 이미지 영역 OCR
    text_density_threshold: float = 5.0            # chars/cm², 이하 시 OCR 후보

    # 신뢰도 기준
    confidence_accept: float = 0.7    # 이상 시 네이티브와 병합 허용
    confidence_warn: float = 0.5      # 이상 0.7 미만: WARN_OCR_DEPENDENCY_HIGH
    # 0.5 미만: OCR 결과 폐기, 네이티브 유지

    # Tesseract 설정
    tesseract_lang: str = "kor+eng"
    tesseract_psm: int = 3            # Page Segmentation Mode

    # 리전 OCR 패딩 (포인트)
    region_padding_pt: float = 2.0
```

### 3.1 기본값 근거

| 옵션 | 기본값 | 근거 |
|------|--------|------|
| `native_text_coverage_threshold` | 0.3 | 텍스트 30% 미만은 스캔본 간주 |
| `confidence_accept` | 0.7 | Tesseract 일반적 신뢰도 기준 |
| `tesseract_lang` | `kor+eng` | 한국어 문서 기본 언어쌍 |

---

## 4. ChunkingOptions

```python
class ChunkStrategy(str, Enum):
    SECTION = "section"             # 섹션 단위
    PARAGRAPH = "paragraph"         # 단락 단위
    SLIDING_WINDOW = "sliding_window"  # 슬라이딩 윈도우
    HYBRID = "hybrid"               # 섹션 우선 + 크기 제한 분할


@dataclass
class ChunkingOptions:
    strategy: ChunkStrategy = ChunkStrategy.HYBRID

    # 크기 제한 (토큰 수 기준)
    max_tokens: int = 512
    min_tokens: int = 50
    overlap_tokens: int = 64        # 슬라이딩 윈도우 겹침

    # 표 청크 설정
    table_summary_enabled: bool = True
    table_record_per_row: bool = True
    table_max_summary_tokens: int = 256

    # 그림 청크 설정
    figure_caption_enabled: bool = True

    # 팩트 청크 설정
    fact_chunk_enabled: bool = True

    # 헤딩 컨텍스트 포함 여부
    heading_context_enabled: bool = True
    heading_context_levels: int = 3  # 상위 N개 헤딩을 컨텍스트로 포함
```

### 4.1 기본값 근거

| 옵션 | 기본값 | 근거 |
|------|--------|------|
| `max_tokens` | 512 | BGE-m3 최적 입력 범위 |
| `overlap_tokens` | 64 | 청크 경계 문맥 보존 |
| `strategy` | `hybrid` | 섹션 구조 + 크기 제한 균형 |

---

## 5. EmbeddingOptions

```python
class EmbeddingProvider(str, Enum):
    BGE_M3 = "bge-m3"           # 기본값 — 한국어 최적화
    OPENAI = "openai"
    E5_LARGE = "e5-large"


@dataclass
class EmbeddingOptions:
    provider: EmbeddingProvider = EmbeddingProvider.BGE_M3

    # BGE-m3 설정
    bge_model_path: str = "BAAI/bge-m3"
    bge_device: str = "cpu"      # "cpu" | "cuda" | "mps"
    bge_batch_size: int = 32
    bge_max_length: int = 8192

    # OpenAI 설정
    openai_model: str = "text-embedding-3-small"
    openai_batch_size: int = 100
    openai_dimensions: int = 1536

    # E5-large 설정
    e5_model_path: str = "intfloat/multilingual-e5-large"
    e5_batch_size: int = 16
    e5_prefix: str = "passage: "  # 패시지 prefix

    # 공통 설정
    normalize_embeddings: bool = True
    retry_max: int = 3
    retry_delay_seconds: float = 1.0
```

### 5.1 프로바이더별 벡터 차원

| 프로바이더 | 차원 | 언어 | 비고 |
|-----------|------|------|------|
| `bge-m3` | 1024 | 다국어 (한국어 최적화) | 기본값, FlagEmbedding |
| `openai` | 1536 | 다국어 | API 키 필요 |
| `e5-large` | 1024 | 다국어 | sentence-transformers |

---

## 6. QualityOptions

```python
@dataclass
class QualityOptions:
    # OCR 의존도 경고 임계값
    ocr_dependency_warn_threshold: float = 0.3   # 페이지의 30% 이상 OCR이면 경고

    # 구조 품질 임계값
    min_section_depth: int = 1
    max_orphan_blocks_ratio: float = 0.2         # 섹션 미소속 블록 허용 비율

    # 표 품질 임계값
    min_table_confidence: float = 0.6
    max_empty_cell_ratio: float = 0.5

    # 청크 품질 임계값
    min_chunk_confidence: float = 0.5

    # 문서 전체 품질 등급 기준
    grade_excellent_threshold: float = 0.9
    grade_good_threshold: float = 0.7
    grade_fair_threshold: float = 0.5
    # 0.5 미만 = poor
```

---

## 7. ExportOptions

```python
@dataclass
class ExportOptions:
    # 출력 파일 선택
    export_canonical_json: bool = True
    export_review_markdown: bool = True
    export_review_json: bool = True
    export_chunks_jsonl: bool = True
    export_records_jsonl: bool = True
    export_facts_jsonl: bool = True
    export_diagnostics_json: bool = True

    # MinIO / S3 설정
    storage_backend: str = "minio"
    bucket_originals: str = "doc-originals"
    bucket_artifacts: str = "doc-artifacts"

    # 파일명 패턴
    artifact_prefix_template: str = "{document_id}/{stage}"
```

---

## 8. LanguageOptions

```python
@dataclass
class LanguageOptions:
    # 주요 처리 언어
    primary_language: str = "ko"      # ISO 639-1

    # 언어 감지 설정
    auto_detect_language: bool = True
    fallback_language: str = "ko"

    # 한국어 정규화 설정
    normalize_korean: bool = True
    normalize_units: bool = True      # 단위 표준화 (km → km, ㎞ → km)
    normalize_numbers: bool = True    # 수치 표기 통일 (1,000 → 1000)
    normalize_dates: bool = True      # 날짜 표기 통일

    # 유니코드 정규화
    unicode_normalization_form: str = "NFC"

    # 엔티티 추출 언어
    ner_languages: list[str] = field(default_factory=lambda: ["ko", "en"])
```

---

## 9. JSON 직렬화 포맷

API로 `ProcessingOptions`를 전달할 때는 아래 JSON 구조를 사용한다.

```json
{
  "pipeline_mode": "FULL_AUTO",
  "ocr": {
    "engine": "tesseract",
    "native_text_coverage_threshold": 0.3,
    "image_area_ratio_threshold": 0.5,
    "text_density_threshold": 5.0,
    "confidence_accept": 0.7,
    "confidence_warn": 0.5,
    "tesseract_lang": "kor+eng",
    "tesseract_psm": 3,
    "region_padding_pt": 2.0
  },
  "chunking": {
    "strategy": "hybrid",
    "max_tokens": 512,
    "min_tokens": 50,
    "overlap_tokens": 64,
    "table_summary_enabled": true,
    "table_record_per_row": true,
    "figure_caption_enabled": true,
    "fact_chunk_enabled": true,
    "heading_context_enabled": true,
    "heading_context_levels": 3
  },
  "embedding": {
    "provider": "bge-m3",
    "bge_device": "cpu",
    "bge_batch_size": 32,
    "normalize_embeddings": true
  },
  "quality": {
    "ocr_dependency_warn_threshold": 0.3,
    "min_table_confidence": 0.6,
    "min_chunk_confidence": 0.5
  },
  "export": {
    "export_canonical_json": true,
    "export_chunks_jsonl": true,
    "export_records_jsonl": true,
    "export_facts_jsonl": true,
    "export_diagnostics_json": true
  },
  "language": {
    "primary_language": "ko",
    "normalize_korean": true,
    "normalize_units": true,
    "normalize_numbers": true,
    "normalize_dates": true,
    "unicode_normalization_form": "NFC"
  }
}
```

---

## 10. 설정 우선순위

설정값은 아래 순서로 덮어쓴다 (낮은 번호가 높은 우선순위):

1. API 요청 페이로드 (`ProcessingOptions` 직접 전달)
2. 컬렉션 레벨 설정 (`collections.default_processing_options`)
3. 시스템 환경 변수 (`PROC_OCR_ENGINE`, `PROC_EMBED_PROVIDER` 등)
4. 코드 기본값 (위 스키마의 `default_factory`)

---

## 11. 환경 변수 매핑

| 환경 변수 | ProcessingOptions 필드 |
|----------|----------------------|
| `PROC_OCR_ENGINE` | `ocr.engine` |
| `PROC_OCR_LANG` | `ocr.tesseract_lang` |
| `PROC_EMBED_PROVIDER` | `embedding.provider` |
| `PROC_EMBED_DEVICE` | `embedding.bge_device` |
| `PROC_CHUNK_MAX_TOKENS` | `chunking.max_tokens` |
| `PROC_PIPELINE_MODE` | `pipeline_mode` |
| `STORAGE_BACKEND` | `export.storage_backend` |
| `OPENAI_API_KEY` | OpenAI 임베딩 인증 (별도 secret) |

---

## 12. 크로스레퍼런스

- adapter_interface_spec (어댑터별 OCR 신호 수집)
- engine_design (13.5 OCR 트리거 기준 — 임계값 원천)
- embedding_plugin_design (EmbeddingProvider 어댑터)
- qdrant_integration (컬렉션별 embedding 설정)
- language_normalization (한국어 정규화 규칙 상세)
