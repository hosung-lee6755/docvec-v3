// 외부 에이전트 토큰을 발급받아 실제로 쓰는 방법. 처음 쓰는 사람이 이 안내만 보고 연결까지 할 수 있게 한다.
import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { mcpConnectCommand } from '../../hooks/useAccessTokens'
import { AGENT_TOOLS, TOKEN_PLACEHOLDER, mcpJsonConfig, mcpServerUrl } from '../../lib/agentConnect'
import { Button } from '../ui'

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [isCopied, setIsCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setIsCopied(true)
      setTimeout(() => setIsCopied(false), 2000)
    } catch {
      // 클립보드를 쓸 수 없는 환경(HTTP 등)에서는 사용자가 직접 선택해 복사한다
      setIsCopied(false)
    }
  }
  return (
    <Button variant="secondary" size="sm" onClick={handleCopy} aria-label={label}
      icon={isCopied ? <Check size={12} /> : <Copy size={12} />}>
      {isCopied ? '복사됨' : '복사'}
    </Button>
  )
}

interface AccessTokenGuideProps {
  mcpPath: string
  /** 아직 토큰이 없으면 처음부터 펼쳐 둔다 */
  isOpenByDefault: boolean
}

export default function AccessTokenGuide({ mcpPath, isOpenByDefault }: AccessTokenGuideProps) {
  const origin = window.location.origin
  const serverUrl = mcpServerUrl(origin, mcpPath)
  const command = mcpConnectCommand(origin, mcpPath, TOKEN_PLACEHOLDER)
  const config = mcpJsonConfig(origin, mcpPath)

  return (
    <section aria-label="사용 방법" className="user-token-guide">
      <details open={isOpenByDefault}>
        <summary className="user-token-guide__summary">사용 방법: 토큰을 발급받아 에이전트에 연결하기</summary>
        <ol className="user-token-guide__steps">
          <li>
            <strong>토큰을 만듭니다.</strong> 아래에서 어느 기기, 어느 도구에서 쓸지 알 수 있게 이름을 붙이고 유효 기간을
            정합니다. 토큰 값은 만든 직후 한 번만 보이므로 바로 복사해 둡니다.
          </li>
          <li>
            <strong>에이전트에 연결합니다.</strong>
            <span className="user-token-guide__label">Claude Code를 쓰면 터미널에서 이 명령을 실행합니다. 토큰을 만들면 실제 값이 들어간 명령을 다시 보여 드립니다.</span>
            <span className="user-token__row">
              <code className="user-token__code">{command}</code>
              <CopyButton text={command} label="연결 명령 예시 복사" />
            </span>
            <span className="user-token-guide__label">
              MCP를 지원하는 다른 도구는 설정에 아래 값을 넣습니다. 설정 화면의 모양은 도구마다 다릅니다.
            </span>
            <dl className="user-token-guide__values">
              <dt>서버 주소</dt>
              <dd><code className="user-token__code">{serverUrl}</code></dd>
              <dt>연결 방식</dt>
              <dd>HTTP (Streamable HTTP)</dd>
              <dt>인증 헤더</dt>
              <dd><code className="user-token__code">Authorization: Bearer {TOKEN_PLACEHOLDER}</code></dd>
            </dl>
            <span className="user-token-guide__label">mcp.json 파일로 설정하는 도구라면 이렇게 넣습니다.</span>
            <div className="user-token__row">
              <pre className="user-token__code user-token-guide__pre">{config}</pre>
              <CopyButton text={config} label="설정 예시 복사" />
            </div>
          </li>
          <li>
            <strong>에이전트에게 평소처럼 요청합니다.</strong> 예를 들어 "사내 문서에서 연차 규정을 찾아 요약해 줘"라고 하면
            에이전트가 아래 기능을 골라 씁니다.
            <table className="user-token-guide__tools">
              <caption className="sr-only">에이전트가 쓸 수 있는 기능</caption>
              <thead><tr><th scope="col">기능</th><th scope="col">하는 일</th></tr></thead>
              <tbody>
                {AGENT_TOOLS.map((tool) => (
                  <tr key={tool.name}>
                    <td>{tool.label} <code>{tool.name}</code></td>
                    <td>{tool.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </li>
        </ol>
        <ul className="user-token-guide__notes">
          <li>에이전트는 이 토큰을 만든 사람과 같은 문서만 볼 수 있고, 모든 조회는 감사 로그에 남습니다.</li>
          <li>토큰은 비밀번호처럼 다룹니다. 다른 사람과 나누거나 코드 저장소에 올리지 않습니다.</li>
          <li>유출이 의심되거나 더 쓰지 않는 토큰은 아래 목록에서 바로 회수합니다. 회수하면 그 에이전트는 즉시 연결이 끊깁니다.</li>
          <li>유효 기간이 지나면 연결이 끊기므로 새 토큰을 만들어 에이전트 설정을 바꿉니다.</li>
          <li>사내 인증서를 쓰는 서버라면 에이전트를 실행하는 PC가 그 인증서를 신뢰해야 연결됩니다.</li>
        </ul>
      </details>
    </section>
  )
}
