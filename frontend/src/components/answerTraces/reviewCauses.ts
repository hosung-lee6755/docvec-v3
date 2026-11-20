import type { ReviewCause } from '../../hooks/useAnswerTraces'

// 답변 문제의 원인(2026-11-20, 개선 루프). 원인마다 고칠 곳이 다르다(검색 설정, 문서 내용, 프롬프트나 모델).
export const REVIEW_CAUSE_LABELS: Record<ReviewCause, string> = {
  retrieval: '검색이 엉뚱한 근거를 가져옴',
  document: '문서 내용이 틀렸거나 없음',
  answer: '근거는 맞지만 답을 잘못 씀',
  other: '기타',
}

// 목록 칸에 쓰는 짧은 이름
export const REVIEW_CAUSE_SHORT: Record<ReviewCause, string> = {
  retrieval: '검색',
  document: '문서',
  answer: '답변 표현',
  other: '기타',
}
