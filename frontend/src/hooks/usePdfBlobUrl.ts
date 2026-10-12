import { useEffect, useRef, useState } from 'react'

interface PdfBlobState {
  sourceKey: string | undefined
  blobUrl: string | undefined
  isError: boolean
}

export interface PdfBlobUrl {
  blobUrl: string | undefined
  isLoading: boolean
  isError: boolean
}

const IDLE: PdfBlobState = { sourceKey: undefined, blobUrl: undefined, isError: false }

// presigned URL 은 서명(쿼리)만 바뀌고 같은 파일을 가리킬 수 있다. 파일의 정체는 쿼리를 뺀 경로다.
const sourceKeyOf = (url: string | undefined): string | undefined => url?.split('?')[0]

/**
 * 원격 PDF 를 한 번만 받아 메모리의 blob URL 로 돌려준다.
 *
 * 원문 대조 탭은 `#page=N` 을 반영하려고 페이지가 바뀔 때마다 iframe 을 다시 만든다.
 * 원격 URL 을 그대로 쓰면 그때마다 PDF 전체를 다시 내려받는다. blob URL 은 메모리에서
 * 읽으므로 네트워크 요청이 없고, 저장된 Content-Type 과 무관하게 application/pdf 로 열린다.
 * 같은 파일의 URL 이 다시 서명돼도(쿼리만 변경) 다시 받지 않는다.
 */
export function usePdfBlobUrl(url: string | undefined): PdfBlobUrl {
  const [state, setState] = useState<PdfBlobState>(IDLE)
  const latestUrl = useRef(url)
  const sourceKey = sourceKeyOf(url)

  // 아래 fetch effect 보다 먼저 선언해, 같은 커밋에서 최신 URL 을 읽게 한다.
  useEffect(() => {
    latestUrl.current = url
  }, [url])

  useEffect(() => {
    const target = latestUrl.current
    if (!sourceKey || !target) return undefined

    const controller = new AbortController()
    let cancelled = false
    let createdUrl: string | undefined

    fetch(target, { signal: controller.signal })
      .then((res) => {
        if (!res.ok) throw new Error(`PDF 를 받지 못했습니다 (${res.status})`)
        return res.blob()
      })
      .then((blob) => {
        if (cancelled) return
        createdUrl = URL.createObjectURL(blob.slice(0, blob.size, 'application/pdf'))
        setState({ sourceKey, blobUrl: createdUrl, isError: false })
      })
      .catch(() => {
        if (!cancelled) setState({ sourceKey, blobUrl: undefined, isError: true })
      })

    return () => {
      cancelled = true
      controller.abort()
      if (createdUrl) URL.revokeObjectURL(createdUrl)
      setState(IDLE)
    }
  }, [sourceKey])

  // 직전 파일의 결과(해제된 blob 포함)가 현재 파일에 보이지 않도록, 현재 파일의 상태일 때만 쓴다.
  const isCurrent = !!sourceKey && state.sourceKey === sourceKey
  return {
    blobUrl: isCurrent ? state.blobUrl : undefined,
    isLoading: !!sourceKey && !isCurrent,
    isError: isCurrent && state.isError,
  }
}
