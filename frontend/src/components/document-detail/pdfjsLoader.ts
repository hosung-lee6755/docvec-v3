// PDF.js 를 원문 대조 탭을 열 때만 불러온다(번들 첫 화면에 넣지 않는다).
export interface PdfViewport {
  width: number
  height: number
}

export interface PdfRenderTask {
  promise: Promise<void>
  cancel: () => void
}

export interface PdfPageProxy {
  getViewport: (options: { scale: number }) => PdfViewport
  render: (options: { canvasContext: CanvasRenderingContext2D; viewport: PdfViewport }) => PdfRenderTask
}

export interface PdfDocumentProxy {
  numPages: number
  getPage: (pageNumber: number) => Promise<PdfPageProxy>
  destroy: () => Promise<void>
}

export async function loadPdfDocument(url: string): Promise<PdfDocumentProxy> {
  const pdfjs = await import('pdfjs-dist')
  const { default: workerSrc } = await import('pdfjs-dist/build/pdf.worker.min.mjs?url')
  // 2026-11-27 전에는 nginx 가 .mjs 를 application/octet-stream 으로 보내 작업 파일이 실행되지 않았다. 그 응답이
  // 브라우저에 1년짜리 캐시로 남아 있을 수 있으므로 주소를 바꿔 새로 받게 한다(nginx 는 쿼리를 보지 않는다)
  pdfjs.GlobalWorkerOptions.workerSrc = `${workerSrc}?mime=js`
  const document = await pdfjs.getDocument({ url }).promise
  return document as unknown as PdfDocumentProxy
}
