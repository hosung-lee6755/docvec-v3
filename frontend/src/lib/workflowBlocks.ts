import {
  LogIn, LogOut, Wand2, Tags, ScanSearch, Hash, AlignLeft,
  ShieldCheck, Split, Merge, Sparkles, type LucideIcon,
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
}

export function getBlockMeta(blockType: string): BlockMeta {
  return BLOCK_META[blockType] ?? {
    label: blockType, description: '', color: '#94a3b8', icon: Sparkles, category: '기타',
  }
}
