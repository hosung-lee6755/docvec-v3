import { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../lib/apiClient'
import { apiErrorDetail } from '../../lib/apiError'
import { Alert, Button, Modal, Spinner } from '../ui'
import { formatPageRange, formatSectionPath } from './citationMeta'

interface PageLocation {
  kind: 'page'
  blob: Blob
  page: number | null
  count: number
}

export interface TextContext {
  chunk_id: string
  located: boolean
  before: string
  text: string
  after: string
  has_more_before: boolean
  has_more_after: boolean
  section_path: string[] | null
  page_start: number | null
  page_end: number | null
}

interface TextLocation {
  kind: 'text'
  context: TextContext
}

type Location = PageLocation | TextLocation

// 쪽 그림을 그릴 수 없는 형식(TXT, HTML 등)은 서버가 422로 알린다. 이때만 글 문맥으로 바꾼다
const NOT_PAGE_RENDERABLE = 422
const NO_CHUNK_REASON = '이 인용은 위치 정보가 없습니다. 예전 답변이거나 표·요약에서 가져온 근거입니다. 같은 질문을 다시 하면 위치를 볼 수 있습니다.'

async function fetchHighlight(documentId: string, chunkId: string): Promise<PageLocation> {
  const res = await apiClient.get(`/documents/${documentId}/chunks/${chunkId}/highlight`, { responseType: 'blob' })
  const page = Number(res.headers['x-highlight-page'])
  return {
    kind: 'page',
    blob: res.data as Blob,
    page: Number.isFinite(page) && page > 0 ? page : null,
    count: Number(res.headers['x-highlight-count']) || 0,
  }
}

async function fetchContext(documentId: string, chunkId: string): Promise<TextLocation> {
  const res = await apiClient.get<TextContext>(`/documents/${documentId}/chunks/${chunkId}/context`)
  return { kind: 'text', context: res.data }
}

// 그림을 요청했으므로 오류 본문도 Blob으로 온다. 서버가 적은 사유를 읽어서 다시 던진다
async function readableError(error: unknown): Promise<unknown> {
  const data = (error as { response?: { data?: unknown } }).response?.data
  if (data instanceof Blob) {
    const detail = await data.text().then((t) => JSON.parse(t).detail as unknown).catch(() => null)
    if (typeof detail === 'string') return new Error(detail)
  }
  return error
}

async function fetchLocation(documentId: string, chunkId: string): Promise<Location> {
  try {
    return await fetchHighlight(documentId, chunkId)
  } catch (error) {
    const status = (error as { response?: { status?: number } }).response?.status
    if (status === NOT_PAGE_RENDERABLE) return fetchContext(documentId, chunkId)
    throw await readableError(error)
  }
}

interface Props {
  documentId: string
  // 예전 답변과 가린 인용에는 없다. 없으면 이유를 달아 버튼을 막아 둔다
  chunkId: string | null | undefined
  filename: string | null
  index: number
}

function TextContextView({ context, label }: { context: TextContext; label: string }) {
  const section = formatSectionPath(context.section_path)
  return (
    <div className="user-chat__cite-context">
      {section && <p className="user-chat__cite-context-path">{section}</p>}
      {!context.located && (
        <Alert tone="info">
          문서 안의 정확한 자리를 찾지 못해 인용한 글만 보여 줍니다. 문서를 고친 뒤 다시 처리했거나 원문과 글이 달라진 경우입니다.
        </Alert>
      )}
      {/* 글은 React가 글자로 그리므로 문서 안의 꺾쇠나 태그는 해석되지 않는다 */}
      <p className="user-chat__cite-context-body" aria-label={label}>
        {context.has_more_before && '… '}
        {context.before}
        <mark>{context.text}</mark>
        {context.after}
        {context.has_more_after && ' …'}
      </p>
    </div>
  )
}

// 인용한 발췌문이 원문의 어느 자리인지 보여 준다. 쪽 그림을 그릴 수 있으면 근거 영역에 색을 입힌 쪽을,
// 그릴 수 없는 형식(TXT, MD, HTML, CSV 등)이면 앞뒤 글과 절 경로를 보여 준다. 버튼을 눌렀을 때만 받는다.
export function CitationLocation({ documentId, chunkId, filename, index }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const location = useQuery({
    queryKey: ['citation-location', documentId, chunkId],
    queryFn: () => fetchLocation(documentId, chunkId as string),
    enabled: isOpen && Boolean(chunkId),
    staleTime: Infinity,
    retry: false,
  })
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const data = location.data
  const blob = data?.kind === 'page' ? data.blob : undefined

  useEffect(() => {
    if (!blob || !isOpen) return undefined
    const url = URL.createObjectURL(blob)
    setImageUrl(url)
    return () => {
      URL.revokeObjectURL(url)
      setImageUrl(null)
    }
  }, [blob, isOpen])

  if (!chunkId) {
    return (
      <span title={NO_CHUNK_REASON}>
        <Button variant="ghost" size="sm" icon={<MapPin size={13} />} disabled aria-label="위치 보기 (사용할 수 없음)">
          위치 보기
        </Button>
      </span>
    )
  }

  const place =
    data?.kind === 'page'
      ? formatPageRange(data.page)
      : data?.kind === 'text'
        ? formatPageRange(data.context.page_start, data.context.page_end)
        : ''
  const title = `[${index}] ${filename ?? '문서'}${place ? ` ${place}` : ''}`

  return (
    <>
      <Button variant="ghost" size="sm" icon={<MapPin size={13} />} onClick={() => setIsOpen(true)}>
        위치 보기
      </Button>
      <Modal isOpen={isOpen} title={title} onClose={() => setIsOpen(false)} size="xl">
        {location.isLoading && <Spinner />}
        {location.isError && (
          <Alert tone="danger">{apiErrorDetail(location.error, '원문 위치를 불러오지 못했습니다.')}</Alert>
        )}
        {data?.kind === 'page' && data.count === 0 && (
          <Alert tone="info">
            이 쪽에서 근거 자리를 특정하지 못해 쪽 전체를 보여 줍니다. 스캔 문서이거나 원문과 추출한 글의 줄바꿈이 다른 경우입니다.
          </Alert>
        )}
        {imageUrl && (
          <div className="user-chat__cite-page">
            <img src={imageUrl} alt={`${title}의 원문. 근거 영역이 노란색으로 표시되어 있습니다.`} />
          </div>
        )}
        {data?.kind === 'text' && <TextContextView context={data.context} label={`${title}의 앞뒤 글`} />}
      </Modal>
    </>
  )
}
