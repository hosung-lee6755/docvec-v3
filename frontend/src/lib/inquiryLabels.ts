import type { InquiryCategory, InquiryStatus } from '../hooks/useInquiries'

// 관리자 문의의 분류와 상태 이름. 화면 여러 곳이 같은 말을 써야 해서 한 곳에 둔다.

export const INQUIRY_CATEGORY_LABELS: Record<InquiryCategory, string> = {
  error: '오류',
  question: '질문',
  request: '요청',
  other: '기타',
}

export const INQUIRY_STATUS_LABELS: Record<InquiryStatus, string> = {
  open: '접수',
  in_progress: '처리 중',
  resolved: '해결됨',
  closed: '종료',
}
