import { useEffect, useState } from 'react'
import { MapPin } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../lib/apiClient'
import { apiErrorDetail } from '../../lib/apiError'
import { Alert, Button, Modal, Spinner } from '../ui'

interface Highlight {
  blob: Blob
  page: number | null
  count: number
}

async function fetchHighlight(documentId: string, chunkId: string): Promise<Highlight> {
  try {
    const res = await apiClient.get(`/documents/${documentId}/chunks/${chunkId}/highlight`, { responseType: 'blob' })
    const page = Number(res.headers['x-highlight-page'])
    return {
      blob: res.data as Blob,
      page: Number.isFinite(page) && page > 0 ? page : null,
      count: Number(res.headers['x-highlight-count']) || 0,
    }
  } catch (error) {
    // 그림을 요청했으므로 오류 본문도 Blob으로 온다. 서버가 적은 사유를 읽어서 다시 던진다
    const data = (error as { response?: { data?: unknown } }).response?.data
    if (data instanceof Blob) {
      const detail = await data.text().then((t) => JSON.parse(t).detail as unknown).catch(() => null)
      if (typeof detail === 'string') throw new Error(detail)
    }
    throw error
  }
}

interface Props {
  documentId: string
  chunkId: string
  filename: string | null
  index: number
}

// 인용한 발췌문이 원문의 어느 자리인지 그 쪽을 그림으로 보여 준다. 근거 영역은 서버가 색을 입혀 보낸다.
// 그림은 버튼을 눌렀을 때만 받는다.
export function CitationLocation({ documentId, chunkId, filename, index }: Props) {
  const [isOpen, setIsOpen] = useState(false)
  const highlight = useQuery({
    queryKey: ['citation-highlight', documentId, chunkId],
    queryFn: () => fetchHighlight(documentId, chunkId),
    enabled: isOpen,
    staleTime: Infinity,
    retry: false,
  })
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const blob = highlight.data?.blob

  useEffect(() => {
    if (!blob || !isOpen) return undefined
    const url = URL.createObjectURL(blob)
    setImageUrl(url)
    return () => {
      URL.revokeObjectURL(url)
      setImageUrl(null)
    }
  }, [blob, isOpen])

  const page = highlight.data?.page
  const title = `[${index}] ${filename ?? '문서'}${page ? ` ${page}쪽` : ''}`

  return (
    <>
      <Button variant="ghost" size="sm" icon={<MapPin size={13} />} onClick={() => setIsOpen(true)}>
        위치 보기
      </Button>
      <Modal isOpen={isOpen} title={title} onClose={() => setIsOpen(false)} size="xl">
        {highlight.isLoading && <Spinner />}
        {highlight.isError && (
          <Alert tone="danger">{apiErrorDetail(highlight.error, '원문 위치를 불러오지 못했습니다.')}</Alert>
        )}
        {highlight.data && highlight.data.count === 0 && (
          <Alert tone="info">
            이 쪽에서 근거 자리를 특정하지 못해 쪽 전체를 보여 줍니다. 스캔 문서이거나 원문과 추출한 글의 줄바꿈이 다른 경우입니다.
          </Alert>
        )}
        {imageUrl && (
          <div className="user-chat__cite-page">
            <img src={imageUrl} alt={`${title}의 원문. 근거 영역이 노란색으로 표시되어 있습니다.`} />
          </div>
        )}
      </Modal>
    </>
  )
}
