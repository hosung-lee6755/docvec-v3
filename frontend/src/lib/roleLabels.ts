// 사용자 역할의 화면 표기. 화면마다 따로 두었다가 viewer가 '뷰어'와 '조회자'로 갈라졌으므로 여기 한 곳에서 정한다.
export const ROLE_LABELS: Record<string, string> = {
  admin: '관리자',
  editor: '편집자',
  viewer: '조회자',
}

export function roleLabel(role: string | null | undefined): string {
  if (!role) return '-'
  return ROLE_LABELS[role] ?? role
}
