import {
  LogIn, LogOut, Wand2, Tags, ScanSearch, Hash, AlignLeft,
  ShieldCheck, Split, Merge, Sparkles, type LucideIcon,
} from 'lucide-react'

export interface BlockMeta {
  label: string
  description: string
  color: string
  icon: LucideIcon
  category: string
  // What the block's 설정(JSON) accepts. Absent = no config needed.
  // Must stay in sync with the backend block implementations
  // (backend/app/pipeline/blocks/*.py).
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
  },
  classify: {
    label: '분류', description: '문서를 사전 정의된 카테고리로 분류합니다.',
    color: '#f472b6', icon: Tags, category: '텍스트 처리',
    configHint: 'categories: 분류할 카테고리 목록. 비워 두면 기본값(보고서/계약서/공문/매뉴얼/기타)을 사용합니다.',
    configExample: { categories: ['민원', '보고서', '기타'] },
  },
  extract_entities: {
    label: '개체 추출', description: '인물·기관·날짜 등 개체명을 추출합니다.',
    color: '#34d399', icon: ScanSearch, category: '텍스트 처리',
  },
  extract_keywords: {
    label: '키워드 추출', description: '핵심 키워드를 추출합니다.',
    color: '#fbbf24', icon: Hash, category: '텍스트 처리',
  },
  summarize: {
    label: '요약', description: '문서 내용을 요약합니다.',
    color: '#60a5fa', icon: AlignLeft, category: '텍스트 처리',
  },
  validate: {
    label: '검증', description: '처리 결과가 기준을 충족하는지 검증합니다.',
    color: '#2dd4bf', icon: ShieldCheck, category: '품질 관리',
    configHint: 'min_text_length: 텍스트 최소 길이(자). 기본 10. 요약/키워드/개체가 비어 있는지도 자동으로 검사합니다.',
    configExample: { min_text_length: 100 },
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
    configHint: 'save_to_document: 결과(요약·키워드 등)를 대상 문서에 저장할지 여부. 기본 true. 실행 기록/JSON 내보내기에는 항상 남습니다.',
    configExample: { save_to_document: false },
  },
}

export function getBlockMeta(blockType: string): BlockMeta {
  return BLOCK_META[blockType] ?? {
    label: blockType, description: '', color: '#94a3b8', icon: Sparkles, category: '기타',
  }
}
