import type { Options } from 'react-markdown'
import remarkGfm from 'remark-gfm'

// remark 구문 트리에서 이 파일이 쓰는 부분만 적은 타입(mdast 를 직접 의존하지 않는다)
interface MdPoint { offset?: number }
interface MdNode {
  type: string
  value?: string
  children?: MdNode[]
  position?: { start: MdPoint; end: MdPoint }
}

/** 목록 항목이 원문에서 쓴 기호("1.", "1)", "-", "- [ ]"). 원문 위치가 없으면 빈 글이다. */
function itemMarker(item: MdNode, source: string): string {
  const start = item.position?.start.offset
  const end = item.children?.[0]?.position?.start.offset ?? item.position?.end.offset
  if (start == null || end == null) return ''
  return source.slice(start, end).trim()
}

/** 목록 항목 하나를 원문 기호가 앞에 붙은 블록들로 바꾼다. */
function itemBlocks(item: MdNode, source: string): MdNode[] {
  const marker = itemMarker(item, source)
  const [first, ...rest] = item.children ?? []
  if (first?.type === 'paragraph') {
    const lead: MdNode = { type: 'text', value: `${marker} ` }
    return [{ ...first, children: [lead, ...(first.children ?? [])] }, ...rest]
  }
  const markerParagraph: MdNode = { type: 'paragraph', children: [{ type: 'text', value: marker }] }
  return first ? [markerParagraph, first, ...rest] : [markerParagraph]
}

/** 목록을 풀어 놓은 새 자식 목록. 안쪽 목록부터 풀어 겹친 목록도 기호가 남는다. */
function flattenLists(children: MdNode[], source: string): MdNode[] {
  return children.flatMap((node) => {
    const flatNode = node.children ? { ...node, children: flattenLists(node.children, source) } : node
    if (flatNode.type !== 'list') return [flatNode]
    return (flatNode.children ?? []).flatMap((item) => itemBlocks(item, source))
  })
}

/**
 * 파싱 본문의 "1.", "1)", "-" 줄을 목록으로 바꾸지 않고 원문 기호 그대로 둔다.
 *
 * 마크다운은 이런 줄을 목록으로 읽는데, 화면 CSS 가 목록 기호를 지우고(list-style: none) 번호도 1부터 다시 매겨
 * 원문의 "3.", "1)", "-" 가 화면에서 사라졌다(2026-11-26). 본문은 원문을 옮긴 글이지 마크다운 목록이 아니므로
 * 항목마다 원문 기호를 앞에 붙인 문단으로 되돌린다.
 */
function remarkLiteralListMarkers() {
  return (tree: MdNode, file: { value?: unknown }) => {
    const source = String(file.value ?? '')
    tree.children = flattenLists(tree.children ?? [], source)
  }
}

// 본문을 평문으로 보이기 위해 끄는 마크다운 문법(micromark 구성 요소 이름). 표(GFM table)와 문단, 표 칸의 "\|"를
// 지키는 역슬래시 이스케이프만 남긴다. 목록은 remarkLiteralListMarkers 가 원문 기호로 되돌린다
const PLAIN_TEXT_DISABLED = [
  'headingAtx', 'setextUnderline', 'blockQuote', 'thematicBreak', 'codeIndented', 'codeFenced', 'codeText',
  'htmlFlow', 'htmlText', 'autolink', 'characterReference', 'attention', 'strikethrough',
  'labelStartLink', 'labelStartImage', 'labelEnd', 'definition',
  'gfmFootnoteDefinition', 'gfmFootnoteCall',
]

/**
 * 파싱 본문의 마크다운처럼 보이는 글을 글 그대로 보인다.
 *
 * 본문은 원문을 옮긴 평문인데 화면이 마크다운으로 읽어 "# 관리자 계정으로 실행" 의 "#", "[평가항목](일반SW개발사업)" 의
 * 괄호 글, "96*96" 사이의 강조 별표가 사라졌다(2026-11-26 전체 문서 렌더링 대조). 마크다운 문법은 표만 쓴다.
 */
function remarkPlainText(this: { data: () => unknown }) {
  const data = this.data() as { micromarkExtensions?: unknown[] }
  data.micromarkExtensions = [...(data.micromarkExtensions ?? []), { disable: { null: PLAIN_TEXT_DISABLED } }]
}

/**
 * 파싱 본문을 그릴 때 쓰는 remark 플러그인.
 *
 * GFM 은 물결표 하나로 감싼 글("~글~")도 취소선으로 그린다. 우리 문서는 "06월 22일~07월 27일"처럼 기간과 범위를
 * 물결표로 적어, 한 줄에 범위가 둘 있으면 그 사이가 취소선이 되었다(만도 보고서, 2026-11-25). 표 등 다른 GFM 문법은 쓰고
 * 물결표 하나짜리 취소선만 끈다. 물결표 둘("~~글~~")은 그대로 취소선이다. 목록 기호는 remarkLiteralListMarkers 가 원문
 * 그대로 남긴다.
 */
export const markdownPlugins: NonNullable<Options['remarkPlugins']> = [
  [remarkGfm, { singleTilde: false }],
  remarkPlainText,
  remarkLiteralListMarkers,
]
