import type { ConfigField } from './workflowBlocks'

// JSON Schema(Pydantic model_json_schema()의 산출물, GET /workflows/block-types의
// config_schema) -> ConfigField[] 변환기. 하드코딩된 configFields가 없는 블록
// 타입(주로 전처리 통합 작업으로 추가된 13종)에 한해 BlockPropertyPanel의 폼을
// 자동 생성하는 데 쓰인다 — 백엔드 Pydantic Config 클래스가 유일한 진실 공급원.

export interface JsonSchemaProperty {
  type?: string
  title?: string
  default?: unknown
  enum?: string[]
  items?: { type?: string }
  anyOf?: JsonSchemaProperty[]
  minimum?: number
  maximum?: number
}

export interface JsonSchema {
  properties?: Record<string, JsonSchemaProperty>
  required?: string[]
}

// 필드별 한글 라벨/도움말/선택지 오버라이드 — 각 블록의 Pydantic Config 클래스
// (backend/app/pipeline/blocks/*.py)를 직접 읽어 필드명 기준으로 작성했다.
// 여기 없는 필드는 JSON Schema의 title을 그대로 라벨로 쓴다.
const FIELD_OVERRIDES: Record<string, Record<string, { label: string; help?: string; placeholder?: string; options?: { value: string; label: string }[] }>> = {
  file_validate: {
    max_file_size_mb: { label: '최대 파일 크기(MB)' },
    allowed_extensions: { label: '허용 확장자', help: '체크한 형식만 허용합니다.', options: [
      { value: '.pdf', label: 'PDF (.pdf)' },
      { value: '.docx', label: 'Word (.docx)' },
      { value: '.hwp', label: '한글 (.hwp)' },
      { value: '.hwpx', label: '한글 (.hwpx)' },
    ] },
    reject_encrypted: { label: '암호화된 파일 거부' },
    reject_duplicates: { label: '중복 파일 거부' },
    max_pages: { label: '최대 페이지 수' },
    scan_malware: { label: '악성코드 검사' },
  },
  text_extract: {
    engine: { label: '추출 엔진', help: 'Docling은 PDF에만 적용됩니다(DOCX/HWP/HWPX는 항상 기존 엔진).', options: [
      { value: 'legacy', label: '기존 엔진 (레거시)' },
      { value: 'docling', label: 'Docling (PDF 전용)' },
    ] },
    extract_tables: { label: '표 추출' },
    extract_images: { label: '이미지 추출' },
    recognize_figures: { label: '그림·도표 설명 인식' },
    max_figures: { label: '최대 그림 개수' },
    exclude_headers_footers: { label: '머리말·꼬리말 제외', help: '페이지마다 반복되는 머리말/꼬리말을 감지해 본문 텍스트에서 제외합니다.' },
    detect_implicit_tables: { label: '선 없는 표 검출', help: '테두리선 없이 정렬만으로 이루어진 표를 검출합니다. 표가 거의 없는 문서군이라면 꺼서 처리 속도를 높일 수 있습니다.' },
    extract_font_signals: { label: '글꼴 신호 추출', help: '줄 단위 글꼴 크기·굵기 등을 추출해 구조 분석(제목 승격, 목차·각주 인식)에 활용합니다. 끄면 구조 분석은 정규식 기반으로만 동작합니다.' },
  },
  ocr: {
    force_ocr: { label: '항상 OCR 실행', help: '텍스트 레이어가 있어도 강제로 OCR을 수행합니다.' },
    engine: { label: 'OCR 엔진', options: [
      { value: 'auto', label: '자동' },
      { value: 'tesseract', label: 'Tesseract' },
    ] },
    language: { label: '인식 언어', options: [
      { value: 'ko+en', label: '한국어 + 영어' },
      { value: 'ko', label: '한국어' },
      { value: 'en', label: '영어' },
    ] },
    deskew: { label: '기울기 보정' },
    denoise: { label: '노이즈 제거' },
    contrast: { label: '대비 보정' },
    grayscale: { label: '흑백 변환' },
    min_confidence: { label: '최소 신뢰도(0~1)' },
  },
  text_clean: {
    collapse_whitespace: { label: '공백·빈 줄 정리' },
    normalize_unicode: { label: '유니코드 정규화(NFC)' },
    normalize_quotes: { label: '따옴표 정규화' },
    normalize_width: { label: '전각→반각 변환' },
    remove_control_chars: { label: '제어문자 제거' },
    remove_repeated_headers: { label: '반복 머리말 제거', help: '페이지마다 반복되는 줄(머리말/꼬리말)을 감지해 제거합니다.' },
    fix_ocr_errors: { label: 'OCR 오류 보정', help: '줄바꿈으로 끊긴 하이픈 단어를 결합하는 등 간단한 보정만 수행합니다.' },
    apply_custom_rules: { label: '커스텀 정제 규칙 적용', help: '정제 규칙 관리 화면에 등록된 규칙을 적용합니다.' },
  },
  stopword: {
    action: { label: '처리 방식', options: [
      { value: 'mark', label: '표시만' },
      { value: 'exclude_from_analysis', label: '분석에서 제외' },
      { value: 'remove', label: '완전 제거' },
    ] },
    scope_filter: { label: '적용 범위 필터', help: '비워 두면 전체 범위(ALL)에 적용합니다.' },
  },
  synonym: {
    processing_mode: { label: '처리 모드', options: [
      { value: 'normalize', label: '정규화' },
      { value: 'tag_only', label: '태그만' },
    ] },
    case_sensitive_default: { label: '기본 대소문자 구분' },
  },
  user_dict: {
    term_types: { label: '적용할 용어 유형', help: '아무것도 체크하지 않으면 전체 유형에 적용합니다.', options: [
      { value: 'TECHNICAL_TERM', label: '전문용어' },
      { value: 'ABBREVIATION', label: '약어' },
      { value: 'ORGANIZATION', label: '조직·기관' },
      { value: 'PERSON', label: '인명' },
      { value: 'PRODUCT', label: '제품' },
      { value: 'PROJECT', label: '프로젝트' },
      { value: 'POLICY', label: '정책·규정' },
      { value: 'CUSTOM', label: '사용자 정의' },
    ] },
    protect_from_stopwords: { label: '불용어 처리로부터 보호', help: '사용자 사전에 등록된 용어는 불용어 처리에서 제외합니다.' },
  },
  structure_analyze: {
    detect_headings: { label: '제목 인식' },
    heading_max_level: { label: '제목 최대 레벨' },
    detect_lists: { label: '목록 인식' },
    detect_toc: { label: '목차 인식' },
    use_font_signals: { label: '글꼴 신호 사용' },
    preserve_clause_number: { label: '조항 번호 보존' },
  },
  pii_detect: {
    entity_types: { label: '탐지할 개체 유형', help: '아무것도 체크하지 않으면 전체 6종을 탐지합니다.', options: [
      { value: 'RRN', label: '주민등록번호' },
      { value: 'PHONE', label: '전화번호' },
      { value: 'EMAIL', label: '이메일' },
      { value: 'ACCOUNT', label: '계좌번호' },
      { value: 'CARD', label: '카드번호' },
      { value: 'NAME', label: '이름' },
    ] },
    action: { label: '처리 방식', options: [
      { value: 'mark_only', label: '표시만' },
      { value: 'mask', label: '마스킹' },
      { value: 'tokenize', label: '토큰화' },
      { value: 'remove', label: '제거' },
      { value: 'exclude_from_embedding', label: '임베딩에서 제외' },
    ] },
    mask_char: { label: '마스킹 문자', options: [
      { value: '*', label: '* (별표)' },
      { value: '#', label: '# (샵)' },
      { value: 'X', label: 'X' },
      { value: '●', label: '● (원)' },
      { value: '-', label: '- (하이픈)' },
    ] },
    require_admin_approval: { label: '관리자 승인 필요' },
  },
  chunk_split: {
    strategy: { label: '분할 전략', help: '비워 두면 컬렉션 기본값을 상속합니다.', options: [
      { value: '', label: '컬렉션 기본값 사용' },
      { value: 'fixed', label: '고정 길이' },
      { value: 'semantic', label: '의미 기준' },
      { value: 'sentence', label: '문장 단위' },
      { value: 'paragraph', label: '문단 단위' },
      { value: 'section_aware', label: '섹션 인식' },
      { value: 'table_unit', label: '표 단위' },
    ] },
    max_tokens: { label: '최대 토큰 수', help: '비워 두면 컬렉션 기본값을 상속합니다.', placeholder: '예: 512' },
    min_tokens: { label: '최소 토큰 수', help: '비워 두면 컬렉션 기본값을 상속합니다.', placeholder: '예: 50' },
    overlap_tokens: { label: '겹침 토큰 수', help: '비워 두면 컬렉션 기본값을 상속합니다.', placeholder: '예: 64' },
    preserve_table: { label: '표 보존' },
    preserve_heading: { label: '제목 보존' },
    include_previous_heading: { label: '상위 제목 포함' },
    split_long_paragraph: { label: '긴 문단 분할' },
  },
  rag_store: {
    embedding_model: { label: '임베딩 모델', help: '비워 두면 컬렉션 기본값을 상속합니다.' },
    exclude_pii: { label: '민감정보 청크 제외', help: '민감정보 탐지에서 임베딩 제외로 표시된 청크는 저장하지 않습니다.' },
    store_masked_text: { label: '마스킹된 텍스트 저장' },
  },
  quality_check: {
    min_extraction_chars: { label: '최소 추출 글자 수' },
    max_broken_char_ratio: { label: '깨진 문자 최대 비율(0~1)' },
    min_ocr_confidence: { label: '최소 OCR 신뢰도(0~1)', help: '문서에 OCR 신뢰도 실측값이 있으면 그 평균을, 없으면 형식 판별 단계의 근사치를 이 기준과 비교합니다.' },
    max_empty_page_ratio: { label: '빈 페이지 최대 비율(0~1)' },
    min_chunk_chars_warning: { label: '청크 최소 글자 경고 기준' },
    max_chunk_chars_warning: { label: '청크 최대 글자 경고 기준' },
    max_implicit_table_ratio: { label: '선 없는 표 최대 비율(0~1)', help: '전체 표 중 테두리선 없이(정렬만으로) 검출된 표의 비율이 이 값을 넘으면 오탐 가능성 경고를 표시합니다.' },
    min_toc_heading_match_ratio: { label: '목차-제목 최소 일치율(0~1)', help: '목차 항목 중 실제 제목 노드와 일치하는 비율이 이 값보다 낮으면 경고를 표시합니다. 목차가 없는 문서에는 적용되지 않습니다.' },
    min_source_recall: { label: '원문 재현율 최소 기준(0~1)', help: '원본 PDF 텍스트 레이어 중 추출 결과에 들어 있어야 하는 비율의 하한입니다. 미만이면 경고하고 점수를 깎습니다. 스캔본·PDF가 아닌 문서는 측정하지 않습니다.' },
    review_policy: { label: '검토 정책', options: [
      { value: 'auto_pass', label: '자동 통과' },
      { value: 'review_on_warning', label: '경고 시 검토' },
      { value: 'always_review', label: '항상 검토' },
    ] },
    fail_below_score: { label: '실패 판정 점수 미만(0~100)' },
  },
}

function _unwrapNullable(prop: JsonSchemaProperty): JsonSchemaProperty {
  if (!prop.anyOf) return prop
  return prop.anyOf.find((branch) => branch.type !== 'null') ?? prop
}

function _fieldType(prop: JsonSchemaProperty): ConfigField['type'] {
  if (prop.enum) return 'select'
  if (prop.type === 'boolean') return 'boolean'
  if (prop.type === 'integer' || prop.type === 'number') return 'number'
  if (prop.type === 'array') return 'list'
  return 'text'
}

export function jsonSchemaToConfigFields(schema: JsonSchema, blockType: string): ConfigField[] {
  const properties = schema.properties ?? {}
  const overrides = FIELD_OVERRIDES[blockType] ?? {}

  return Object.entries(properties).map(([key, rawProp]) => {
    const prop = _unwrapNullable(rawProp)
    const override = overrides[key]
    const options = override?.options ?? (prop.enum
      ? prop.enum.map((v) => ({ value: v, label: v }))
      : undefined)

    const field: ConfigField = {
      key,
      label: override?.label ?? rawProp.title ?? key,
      // 배열 필드에 고정 선택지가 있으면 다중 선택(list + options), 스칼라면 단일 선택.
      type: options && prop.type !== 'array' ? 'select' : _fieldType(prop),
      default: rawProp.default,
      help: override?.help,
      placeholder: override?.placeholder,
      options,
      min: prop.minimum,
      max: prop.maximum,
    }
    return field
  })
}
