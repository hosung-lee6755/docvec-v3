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
  pdfjs.GlobalWorkerOptions.workerSrc = workerSrc
  const document = await pdfjs.getDocument({ url }).promise
  return document as unknown as PdfDocumentProxy
}
