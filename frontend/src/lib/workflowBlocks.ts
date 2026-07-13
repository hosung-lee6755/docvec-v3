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
  },
  branch: {
    label: '조건 분기', description: '조건에 따라 흐름을 분기합니다.',
    color: '#fb923c', icon: Split, category: '흐름 제어',
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
  },
}

export function getBlockMeta(blockType: string): BlockMeta {
  return BLOCK_META[blockType] ?? {
    label: blockType, description: '', color: '#94a3b8', icon: Sparkles, category: '기타',
  }
}
