import {
  LogIn, LogOut, Wand2, Tags, ScanSearch, Hash, AlignLeft,
  ShieldCheck, Split, Merge, Sparkles, type LucideIcon,
  FileCheck, FileSearch, FileText, ScanText, Eraser, Ban,
  ArrowLeftRight, Tag, Network, ShieldAlert, Scissors, Database, CheckCircle,
} from 'lucide-react'

// One typed form field in the block property panel, persisted into the
// block's config dict. Must stay in sync with the backend block
// implementations (backend/app/pipeline/blocks/*.py).
export interface ConfigField {
  key: string
  label: string
  type: 'boolean' | 'number' | 'text' | 'textarea' | 'list' | 'select'
  default?: unknown
  help?: string
  placeholder?: string
  options?: { value: string; label: string }[]
  min?: number
  max?: number
}

export interface BlockMeta {
  label: string
  description: string
  color: string
  icon: LucideIcon
  category: string
  // Typed config fields rendered as a form. Absent/empty = no config needed.
  configFields?: ConfigField[]
  // Free-text note shown when there are no form fields but something still
  // needs explaining (e.g. 조건 분기's edge-condition rule).
  configHint?: string
  configExample?: Record<string, unknown>
}

export const BLOCK_CATEGORIES = ['입출력', '텍스트 처리', '품질 관리', '흐름 제어', '마무리'] as const

// PREPROCESS 워크플로우 팔레트가 쓰는 카테고리 — 각 블록 클래스의 category
// 프로퍼티(backend/app/pipeline/blocks/*.py)와 정확히 일치해야 한다.
export const PREPROCESS_BLOCK_CATEGORIES = ['입력·추출', '정제·정규화', '구조·보호', '분할·저장', '품질·제어'] as const

export const BLOCK_META: Record<string, BlockMeta> = {
  input: {
    label: '입력', description: '문서 원본을 워크플로우에 공급합니다.',
    color: '#38bdf8', icon: LogIn, category: '입출력',
  },
  preprocess: {
    label: '전처리', description: '텍스트를 정제하고 정규화합니다.',
    color: '#a78bfa', icon: Wand2, category: '텍스트 처리',
    configFields: [
      { key: 'collapse_whitespace', label: '공백·빈 줄 정리', type: 'boolean', default: true, help: '연속 공백을 하나로, 3줄 이상 빈 줄을 정리합니다.' },
      { key: 'remove_urls', label: 'URL 제거', type: 'boolean', default: false },
      { key: 'remove_emails', label: '이메일 주소 제거', type: 'boolean', default: false },
      { key: 'remove_special_chars', label: '특수문자 제거', type: 'boolean', default: false, help: '한글·영문·숫자·기본 문장부호만 남깁니다.' },
    ],
  },
  classify: {
    label: '분류', description: '문서를 사전 정의된 카테고리로 분류합니다.',
    color: '#f472b6', icon: Tags, category: '텍스트 처리',
    configFields: [
      {
        key: 'categories', label: '분류 카테고리', type: 'list',
        placeholder: '민원, 보고서, 기타',
        help: '쉼표로 구분해 입력하세요. LLM이 이 중 가장 맞는 하나를 고릅니다. 비워 두면 보고서/계약서/공문/매뉴얼/기타.',
      },
    ],
  },
  extract_entities: {
    label: '개체 추출', description: '인물·기관·날짜 등 개체명을 추출합니다.',
    color: '#34d399', icon: ScanSearch, category: '텍스트 처리',
    configFields: [
      { key: 'max_entities', label: '최대 개수', type: 'number', default: 15, min: 1, max: 30 },
      {
        key: 'entity_types', label: '추출할 개체 유형', type: 'list',
        placeholder: '인명, 기관명, 지명, 제품명, 날짜',
        help: '쉼표로 구분. 비워 두면 인명/기관명/지명/제품명/날짜.',
      },
    ],
  },
  extract_keywords: {
    label: '키워드 추출', description: '핵심 키워드를 추출합니다.',
    color: '#fbbf24', icon: Hash, category: '텍스트 처리',
    configFields: [
      { key: 'max_keywords', label: '최대 개수', type: 'number', default: 10, min: 1, max: 30 },
    ],
  },
  summarize: {
    label: '요약', description: '문서 내용을 요약합니다.',
    color: '#60a5fa', icon: AlignLeft, category: '텍스트 처리',
    configFields: [
      {
        key: 'format', label: '요약 형식', type: 'select', default: 'paragraph',
        options: [
          { value: 'paragraph', label: '문단형' },
          { value: 'bullets', label: '글머리표 목록' },
        ],
      },
      {
        key: 'prompt', label: '추가 지시문 (선택)', type: 'textarea',
        placeholder: '예: 3문장 이내로 요약하고, 금액과 날짜는 반드시 포함하세요.',
        help: 'LLM에게 전달할 요약 지시를 자유롭게 입력합니다.',
      },
    ],
  },
  validate: {
    label: '검증', description: '처리 결과가 기준을 충족하는지 검증합니다.',
    color: '#2dd4bf', icon: ShieldCheck, category: '품질 관리',
    configFields: [
      {
        key: 'min_text_length', label: '텍스트 최소 길이(자)', type: 'number', default: 10, min: 1,
        help: '요약/키워드/개체가 비어 있는지는 항상 자동으로 검사합니다.',
      },
    ],
  },
  branch: {
    label: '조건 분기', description: '조건에 따라 흐름을 분기합니다.',
    color: '#fb923c', icon: Split, category: '흐름 제어',
    configHint: '분기 조건은 이 블록이 아니라 나가는 연결선(엣지)의 condition에 설정합니다. 예: {"output_field": "is_valid", "equals": true} — 상류 출력의 해당 필드가 일치하는 연결선만 따라갑니다.',
  },
  merge: {
    label: '병합', description: '여러 갈래의 흐름을 하나로 합칩니다.',
    color: '#22d3ee', icon: Merge, category: '흐름 제어',
  },
  postprocess: {
    label: '후처리', description: '최종 출력 전에 결과를 다듬습니다.',
    color: '#c084fc', icon: Sparkles, category: '마무리',
  },
  output: {
    label: '출력', description: '처리된 결과를 워크플로우 밖으로 내보냅니다.',
    color: '#4ade80', icon: LogOut, category: '입출력',
    configFields: [
      {
        key: 'save_to_document', label: '결과를 문서에 저장', type: 'boolean', default: true,
        help: '요약·키워드 등을 대상 문서에 반영합니다. 끄더라도 실행 기록/JSON 내보내기에는 항상 남습니다.',
      },
    ],
  },

  // 아래 13종은 전처리 워크플로우 통합 작업으로 추가된 실제 PREPROCESS 파이프라인
  // 블록 — label은 백엔드 BLOCK_TYPE_LABELS(app/pipeline/blocks/registry.py)와
  // 동일하게 유지한다. configFields는 의도적으로 비워 둔다 — BlockPropertyPanel이
  // /workflows/block-types의 config_schema(JSON Schema)를 blockConfigSchema.ts로
  // 변환해 자동 생성한 폼으로 대체한다.
  file_validate: {
    label: '파일 검증', description: '업로드된 파일의 형식·크기·암호화 여부를 검사합니다.',
    color: '#0ea5e9', icon: FileCheck, category: '입력·추출',
  },
  format_detect: {
    label: '형식 판별', description: '파일의 실제 포맷을 판별해 이후 추출 방식을 결정합니다.',
    color: '#0ea5e9', icon: FileSearch, category: '입력·추출',
  },
  text_extract: {
    label: '텍스트 추출', description: '문서에서 본문·표·이미지 설명을 추출합니다.',
    color: '#0ea5e9', icon: FileText, category: '입력·추출',
  },
  // 실제 OCR은 텍스트 추출 블록이 호출하는 어댑터(pdf_adapter.py)가 페이지별
  // 커버리지를 보고 자동으로 수행한다 — 이 블록은 그래프에 배치해도 상류 출력을
  // 그대로 통과시키기만 하는 자리표시자(OcrBlock 독스트링, 통합 설계서 §3.3④)라
  // configFields를 비워 두지 않고 명시적으로 []로 고정해 스키마 기반 설정폼 대신
  // 이 사실을 알리는 configHint만 보이게 한다.
  ocr: {
    label: 'OCR (자동 적용됨)',
    description: '별도 배치·설정 없이 텍스트 추출 단계에서 스캔 여부를 자동 판단해 이미 수행됩니다.',
    color: '#0ea5e9', icon: ScanText, category: '입력·추출',
    configFields: [],
    configHint: 'OCR은 텍스트 추출 블록이 자동으로 수행하므로 이 블록의 설정은 실행에 반영되지 않습니다.',
  },
  text_clean: {
    label: '텍스트 정제', description: '공백·특수문자를 정규화하고 커스텀 정제 규칙을 적용합니다.',
    color: '#a78bfa', icon: Eraser, category: '정제·정규화',
  },
  stopword: {
    label: '불용어 처리', description: '사전에 등록된 불용어를 표시하거나 제외합니다.',
    color: '#a78bfa', icon: Ban, category: '정제·정규화',
  },
  synonym: {
    label: '동의어 정규화', description: '동의어를 대표 용어로 정규화하거나 검색을 확장합니다.',
    color: '#a78bfa', icon: ArrowLeftRight, category: '정제·정규화',
  },
  user_dict: {
    label: '사용자 사전 적용', description: '사용자 사전의 전문용어·별칭을 인식하고 정규화합니다.',
    color: '#a78bfa', icon: Tag, category: '정제·정규화',
  },
  structure_analyze: {
    label: '구조 분석', description: '제목·목록 등 문서의 구조적 요소를 인식합니다.',
    color: '#f97316', icon: Network, category: '구조·보호',
  },
  pii_detect: {
    label: '민감정보 탐지', description: '주민번호·연락처 등 민감정보를 탐지하고 보호 조치를 적용합니다.',
    color: '#f97316', icon: ShieldAlert, category: '구조·보호',
  },
  chunk_split: {
    label: '문서 분할', description: '문서를 검색·임베딩 단위(청크)로 분할합니다.',
    color: '#eab308', icon: Scissors, category: '분할·저장',
  },
  rag_store: {
    label: 'RAG 저장', description: '분할된 청크를 임베딩해 벡터 DB에 저장합니다.',
    color: '#eab308', icon: Database, category: '분할·저장',
  },
  quality_check: {
    label: '품질 검증', description: '추출·OCR·청크 품질을 점검하고 검토 필요 여부를 판정합니다.',
    color: '#22c55e', icon: CheckCircle, category: '품질·제어',
  },
}

export function getBlockMeta(blockType: string): BlockMeta {
  return BLOCK_META[blockType] ?? {
    label: blockType, description: '', color: '#94a3b8', icon: Sparkles, category: '기타',
  }
}
