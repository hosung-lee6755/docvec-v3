// 업로드 화면에서 받는 문서 형식. 백엔드 app/pipeline/formats.py의 EXTENSION_CONTENT_TYPES와 같게 유지한다.
export const DOCUMENT_EXTENSIONS = [
  '.pdf', '.hwp', '.hwpx', '.docx', '.xlsx', '.csv', '.pptx', '.txt', '.md', '.html', '.htm',
  '.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp', '.webp',
] as const

export const ZIP_EXTENSIONS = ['.zip'] as const

export function hasExtension(name: string, extensions: readonly string[]): boolean {
  const dot = name.lastIndexOf('.')
  return dot >= 0 && extensions.includes(name.slice(dot).toLowerCase())
}
