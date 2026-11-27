import { Briefcase, FileText, FolderOpen } from 'lucide-react'
import { formatCitationPlace, type CitationPlace } from './citationMeta'

export interface SourcePlaceProps extends CitationPlace {
  project_name?: string | null
  collection_name?: string | null
  filename?: string | null
}

// 근거의 출처 한 줄: 프로젝트 · 컬렉션 · 문서 · 쪽과 절 경로. 채팅 인용과 검색 결과가 같은 모양으로 보인다(2026-11-27)
export function SourcePlace({ project_name, collection_name, filename, ...place }: SourcePlaceProps) {
  const where = formatCitationPlace(place)
  return (
    <>
      {project_name && (
        <span className="user-chat__cite-file" title="프로젝트">
          <Briefcase size={12} aria-hidden="true" />
          {project_name}
        </span>
      )}
      {collection_name && (
        <span className="user-chat__cite-file" title="컬렉션">
          <FolderOpen size={12} aria-hidden="true" />
          {collection_name}
        </span>
      )}
      <span className="user-chat__cite-file" title="문서">
        <FileText size={12} aria-hidden="true" />
        {filename ?? '문서'}
      </span>
      {where && <span title="쪽과 문서 구조 위치">{where}</span>}
    </>
  )
}
