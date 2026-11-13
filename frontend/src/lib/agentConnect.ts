// 외부 에이전트(MCP 클라이언트) 연결 안내에 쓰는 주소, 설정 예시, 도구 설명.
// 도구 목록은 backend/app/mcp/tools.py의 TOOLS와 같아야 한다.

export const TOKEN_PLACEHOLDER = '<발급받은 토큰>'

export interface AgentTool {
  name: string
  label: string
  description: string
}

export const AGENT_TOOLS: AgentTool[] = [
  { name: 'list_collections', label: '컬렉션 목록', description: '내가 볼 수 있는 컬렉션과 프로젝트를 알려 줍니다. 검색 범위를 정할 때 씁니다.' },
  { name: 'search_documents', label: '문서 검색', description: '사내 문서에서 관련 단락을 찾습니다. 내가 볼 수 있는 문서만 나옵니다.' },
  { name: 'read_chunk', label: '단락 읽기', description: '검색으로 찾은 단락의 전문과 쪽 번호, 앞뒤 단락을 읽습니다.' },
  { name: 'read_document', label: '문서 읽기', description: '문서 하나를 처음부터 차례대로 읽습니다.' },
  { name: 'ask', label: '답변 받기', description: '질문하면 사내 문서를 찾아 근거를 붙여 답합니다. 수십 초 걸리고, 복합 질문은 심층 검색으로 몇 분 걸릴 수 있습니다.' },
]

export function mcpServerUrl(origin: string, path: string): string {
  return `${origin}${path}`
}

/** mcp.json 형식(서버 이름 아래 url과 headers)을 쓰는 도구에 붙여 넣을 설정. */
export function mcpJsonConfig(origin: string, path: string, token: string = TOKEN_PLACEHOLDER): string {
  return JSON.stringify(
    {
      mcpServers: {
        docvec: { type: 'http', url: mcpServerUrl(origin, path), headers: { Authorization: `Bearer ${token}` } },
      },
    },
    null,
    2,
  )
}
