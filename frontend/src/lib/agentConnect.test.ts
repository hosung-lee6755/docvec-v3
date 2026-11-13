import { describe, expect, it } from 'vitest'
import { AGENT_TOOLS, TOKEN_PLACEHOLDER, mcpJsonConfig, mcpServerUrl } from './agentConnect'

describe('mcpServerUrl', () => {
  it('접속 주소와 MCP 경로를 이어 서버 주소를 만든다', () => {
    expect(mcpServerUrl('https://192.168.0.3:13443', '/api/v1/mcp')).toBe('https://192.168.0.3:13443/api/v1/mcp')
  })
})

describe('mcpJsonConfig', () => {
  it('주소와 인증 헤더를 담은 mcp.json 형식 설정을 만든다', () => {
    const config = JSON.parse(mcpJsonConfig('https://h', '/api/v1/mcp', 'dvp_x'))
    expect(config.mcpServers.docvec).toEqual({
      type: 'http', url: 'https://h/api/v1/mcp', headers: { Authorization: 'Bearer dvp_x' },
    })
  })

  it('토큰이 없으면 자리 표시 문구를 넣는다', () => {
    expect(mcpJsonConfig('https://h', '/api/v1/mcp')).toContain(`Bearer ${TOKEN_PLACEHOLDER}`)
  })
})

describe('AGENT_TOOLS', () => {
  it('서버가 제공하는 도구 다섯 가지를 모두 설명한다', () => {
    expect(AGENT_TOOLS.map((t) => t.name)).toEqual([
      'list_collections', 'search_documents', 'read_chunk', 'read_document', 'ask',
    ])
    expect(AGENT_TOOLS.every((t) => t.description.length > 0)).toBe(true)
  })
})
