import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, renderHook, waitFor } from '@testing-library/react'
import { usePdfBlobUrl } from './usePdfBlobUrl'

// 원문 대조 탭은 페이지를 넘길 때마다 iframe 을 다시 만든다. 원격 URL 을 그대로 쓰면 그때마다
// PDF 전체를 다시 내려받으므로, 한 번만 받아 메모리의 blob URL 로 띄운다.
describe('usePdfBlobUrl', () => {
  const createObjectURL = vi.fn()
  const revokeObjectURL = vi.fn()
  const fetchMock = vi.fn()

  const okResponse = () => ({ ok: true, blob: async () => new Blob(['%PDF-1.7']) })

  beforeEach(() => {
    createObjectURL.mockReset().mockReturnValue('blob:mem/abc')
    revokeObjectURL.mockReset()
    fetchMock.mockReset().mockImplementation(async () => okResponse())
    vi.stubGlobal('fetch', fetchMock)
    // jsdom 에는 createObjectURL 이 없다. 전역 URL 객체를 건드리지 않고 이 테스트 동안만 붙였다 뗀다.
    Object.defineProperty(URL, 'createObjectURL', { value: createObjectURL, configurable: true, writable: true })
    Object.defineProperty(URL, 'revokeObjectURL', { value: revokeObjectURL, configurable: true, writable: true })
  })

  afterEach(() => {
    // 스텁을 떼기 전에 먼저 언마운트해야, 정리 단계의 revokeObjectURL 호출이 스텁에 닿는다.
    cleanup()
    vi.unstubAllGlobals()
    Reflect.deleteProperty(URL, 'createObjectURL')
    Reflect.deleteProperty(URL, 'revokeObjectURL')
  })

  it('url 이 없으면 아무것도 받지 않는다', () => {
    const { result } = renderHook(() => usePdfBlobUrl(undefined))

    expect(fetchMock).not.toHaveBeenCalled()
    expect(result.current).toEqual({ blobUrl: undefined, isLoading: false, isError: false })
  })

  it('PDF 를 한 번 받아 application/pdf blob URL 을 돌려준다', async () => {
    const { result } = renderHook(() => usePdfBlobUrl('http://minio/o.pdf?sig=1'))

    expect(result.current.isLoading).toBe(true)
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/abc'))

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toBe('http://minio/o.pdf?sig=1')
    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/pdf')
    expect(result.current.isLoading).toBe(false)
  })

  it('다시 렌더링해도 같은 url 이면 다시 받지 않는다', async () => {
    const { result, rerender } = renderHook(() => usePdfBlobUrl('http://minio/o.pdf?sig=1'))
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/abc'))

    rerender()
    rerender()

    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('같은 파일의 서명만 바뀐 url 이면 다시 받지 않는다', async () => {
    const { result, rerender } = renderHook(({ url }) => usePdfBlobUrl(url), {
      initialProps: { url: 'http://minio/o.pdf?X-Amz-Signature=aaa' },
    })
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/abc'))

    rerender({ url: 'http://minio/o.pdf?X-Amz-Signature=bbb' })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(result.current.blobUrl).toBe('blob:mem/abc')
    expect(revokeObjectURL).not.toHaveBeenCalled()
  })

  it('언마운트하면 blob URL 을 해제한다', async () => {
    const { result, unmount } = renderHook(() => usePdfBlobUrl('http://minio/o.pdf?sig=1'))
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/abc'))

    unmount()

    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mem/abc')
  })

  it('파일이 바뀌면 이전 blob URL 을 해제하고 새로 받는다', async () => {
    createObjectURL.mockReturnValueOnce('blob:mem/first').mockReturnValueOnce('blob:mem/second')
    const { result, rerender } = renderHook(({ url }) => usePdfBlobUrl(url), {
      initialProps: { url: 'http://minio/a.pdf' },
    })
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/first'))

    rerender({ url: 'http://minio/b.pdf' })

    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/second'))
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mem/first')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('url 이 잠깐 사라졌다 돌아와도 해제된 blob URL 을 돌려주지 않는다', async () => {
    createObjectURL.mockReturnValueOnce('blob:mem/first').mockReturnValueOnce('blob:mem/second')
    const { result, rerender } = renderHook(({ url }) => usePdfBlobUrl(url), {
      initialProps: { url: 'http://minio/a.pdf' as string | undefined },
    })
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/first'))

    rerender({ url: undefined })
    rerender({ url: 'http://minio/a.pdf' })

    expect(result.current.blobUrl).not.toBe('blob:mem/first')
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/second'))
  })

  it('받는 도중 파일이 바뀌면 늦게 도착한 이전 응답으로 blob 을 만들지 않는다', async () => {
    let resolveFirst: (r: unknown) => void = () => {}
    fetchMock
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementation(async () => okResponse())
    createObjectURL.mockReturnValue('blob:mem/b-only')
    const { result, rerender } = renderHook(({ url }) => usePdfBlobUrl(url), {
      initialProps: { url: 'http://minio/a.pdf' },
    })

    rerender({ url: 'http://minio/b.pdf' })
    await waitFor(() => expect(result.current.blobUrl).toBe('blob:mem/b-only'))
    resolveFirst(okResponse())
    await Promise.resolve()

    expect(createObjectURL).toHaveBeenCalledTimes(1)
  })

  it('받기 전에 언마운트하면 요청을 중단하고 blob 을 만들지 않는다', async () => {
    let signal: AbortSignal | undefined
    fetchMock.mockImplementationOnce((_url: string, init?: RequestInit) => {
      signal = init?.signal ?? undefined
      return new Promise(() => {})
    })
    const { unmount } = renderHook(() => usePdfBlobUrl('http://minio/o.pdf?sig=1'))

    unmount()

    expect(signal?.aborted).toBe(true)
    expect(createObjectURL).not.toHaveBeenCalled()
  })

  it('받기에 실패하면 isError 를 알린다', async () => {
    fetchMock.mockImplementation(async () => ({ ok: false, status: 403 }))
    const { result } = renderHook(() => usePdfBlobUrl('http://minio/o.pdf?sig=1'))

    await waitFor(() => expect(result.current.isError).toBe(true))

    expect(result.current.blobUrl).toBeUndefined()
    expect(result.current.isLoading).toBe(false)
  })
})
