// 인용 머리줄에 보일 위치 글. 쪽 번호만으로는 문서 안의 자리를 알 수 없어 절 경로를 함께 보인다.
export interface CitationPlace {
  page_number?: number | null
  page_end?: number | null
  section_path?: string[] | null
}

const SECTION_SEPARATOR = ' > '

export function formatPageRange(pageNumber?: number | null, pageEnd?: number | null): string {
  if (!pageNumber) return ''
  return pageEnd && pageEnd > pageNumber ? `${pageNumber}–${pageEnd}쪽` : `${pageNumber}쪽`
}

export function formatSectionPath(path?: string[] | null): string {
  return (path ?? []).map((part) => part.trim()).filter(Boolean).join(SECTION_SEPARATOR)
}

/** "3쪽 · 2장 운영 > 2.1 백업". 아는 정보가 없으면 빈 글이다. */
export function formatCitationPlace(place: CitationPlace): string {
  return [formatPageRange(place.page_number, place.page_end), formatSectionPath(place.section_path)]
    .filter(Boolean)
    .join(' · ')
}
