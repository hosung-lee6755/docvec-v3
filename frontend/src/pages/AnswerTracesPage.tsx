import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Loader2, ShieldOff, Route, X } from 'lucide-react'
import {
  useAnswerTrace,
  useAnswerTraces,
  type AnswerTraceSource,
  type Grounding,
  type SourceAccess,
} from '../hooks/useAnswerTraces'
import { useAuthStore } from '../store/authStore'
import { DeepSearchSteps } from '../components/chat/DeepSearch'

const PAGE_SIZE = 50

const GROUNDING_LABELS: Record<Grounding, string> = {
  passed: '근거 확인',
  failed: '근거 부족',
  skipped: '검증 안 함',
}

const ACCESS_LABELS: Record<SourceAccess, string> = {
  visible: '열람 가능',
  hidden: '열람 권한 없음',
  deleted: '삭제된 문서',
}

const PROMPT_SOURCE_LABELS: Record<string, string> = {
  project: '프로젝트 지정',
  user: '사용자 지정',
  default: '기본',
}

const muted = { color: 'var(--color-text-muted)' }

function formatTime(value: string): string {
  return new Date(value).toLocaleString('ko-KR')
}

function SourceCard({ source }: { source: AnswerTraceSource }) {
  const hiddenText =
    source.access === 'visible'
      ? '현재 본문을 찾을 수 없습니다(표 행·캐시 인용이거나 재처리로 청크가 바뀜).'
      : ACCESS_LABELS[source.access]
  return (
    <li style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', listStyle: 'none' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-3)', fontSize: 12, ...muted }}>
        <strong style={{ color: 'inherit' }}>[{source.rank}]</strong>
        {source.access === 'visible' ? (
          <>
            <span>{source.filename ?? '이름 없음'}</span>
            {source.page_number ? <span>{source.page_number}쪽</span> : null}
            <span>등급 {source.security_level ?? '-'}</span>
          </>
        ) : (
          <span>문서 정보 비공개</span>
        )}
        <span>{source.cited ? '답변에 인용됨' : '인용 안 됨'}</span>
        <span className={`krds-badge small ${source.access === 'visible' ? 'bg-success' : 'bg-warning'}`}>
          {ACCESS_LABELS[source.access]}
        </span>
        {source.text_changed && <span className="krds-badge small bg-warning">답변 이후 문서가 바뀜</span>}
      </div>
      <p style={{ margin: 'var(--space-2) 0 0', fontSize: 13, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
        {source.text ?? <span style={muted}>{hiddenText}</span>}
      </p>
    </li>
  )
}

function TraceDetail({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const { data, isLoading, isError } = useAnswerTrace(traceId)
  if (isLoading) return <Loader2 size={20} aria-label="불러오는 중" />
  if (isError || !data) return <p role="alert">추적 기록을 불러오지 못했습니다.</p>

  const facts: [string, string][] = [
    ['질문한 사람', `${data.username ?? '(삭제된 사용자)'} · 역할 ${data.user_role ?? '-'} · 열람등급 ${data.clearance_level ?? '-'}`],
    ['권한 맥락', `소속 그룹 ${data.group_ids.length}개 · 접근 가능 컬렉션 ${data.accessible_collection_count}개`],
    ['질문 방식', data.mode === 'deep' ? '심층 검색(하위 질문으로 나눠 찾은 뒤 종합)' : '일반'],
    ['질문 경로', data.channel === 'mcp' ? `외부 에이전트(토큰 ${data.access_token_id ?? '삭제됨'})` : '채팅 화면'],
    ['모델', `${data.model_key ?? '-'} (${data.provider ?? '-'}) · 검증 모델 ${data.verifier_model ?? '-'}`],
    ['근거 검증', `${data.grounding ? GROUNDING_LABELS[data.grounding] : '-'}${data.broadened ? ' · 재검색함' : ''}${data.cache_hit ? ' · 캐시 재사용' : ''}`],
    ['시스템 프롬프트', PROMPT_SOURCE_LABELS[data.system_prompt_source ?? ''] ?? '-'],
    ['토큰·응답 시간', `${data.input_tokens ?? '-'} / ${data.output_tokens ?? '-'} · ${data.latency_ms ?? '-'}ms`],
  ]

  return (
    <section aria-label="답변 추적 상세" style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-4)', marginTop: 'var(--space-4)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>답변 추적 상세</h2>
        <button type="button" className="krds-btn text small" onClick={onClose} aria-label="상세 닫기"><X size={16} /></button>
      </div>
      <p style={{ fontSize: 12, ...muted }}>{formatTime(data.created_at)} · 이 화면을 연 기록은 감사 로그에 남습니다.</p>

      <dl style={{ display: 'grid', gridTemplateColumns: '140px 1fr', gap: '6px var(--space-3)', fontSize: 13 }}>
        {facts.map(([label, value]) => (
          <div key={label} style={{ display: 'contents' }}>
            <dt style={muted}>{label}</dt>
            <dd style={{ margin: 0 }}>{value}</dd>
          </div>
        ))}
      </dl>

      <h3 style={{ fontSize: 14, marginTop: 'var(--space-4)' }}>질문</h3>
      <p style={{ whiteSpace: 'pre-wrap' }}>{data.query}</p>
      <h3 style={{ fontSize: 14 }}>답변 <span className="krds-badge small bg-information">AI가 생성한 답변</span></h3>
      <p style={{ whiteSpace: 'pre-wrap' }}>{data.answer ?? data.error_message ?? '-'}</p>

      {data.agent_steps && <DeepSearchSteps steps={data.agent_steps} defaultOpen />}

      <h3 style={{ fontSize: 14 }}>근거로 넣은 발췌문 ({data.sources.length})</h3>
      <p style={{ fontSize: 12, ...muted }}>본문과 파일명은 지금 내가 볼 수 있는 문서만 보입니다. 관리자도 문서 열람 권한을 건너뛰지 않습니다.</p>
      <ul style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 0 }}>
        {data.sources.map((s) => <SourceCard key={s.rank} source={s} />)}
      </ul>
    </section>
  )
}

export default function AnswerTracesPage() {
  const currentUser = useAuthStore((s) => s.user)
  const [searchParams] = useSearchParams()
  const [grounding, setGrounding] = useState<Grounding | ''>('')
  const [documentId, setDocumentId] = useState(searchParams.get('document_id') ?? '')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)

  const { data, isLoading, isError } = useAnswerTraces({
    grounding: grounding || undefined,
    document_id: documentId.trim() || undefined,
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  })

  if (currentUser?.role !== 'admin') {
    return (
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', ...muted }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const items = data?.items ?? []

  return (
    <div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-2)' }}>답변 추적</h1>
      <p style={{ ...muted, marginBottom: 'var(--space-4)' }}>
        채팅 답변마다 누가 어떤 권한으로 물었고 어떤 문서를 근거로 받았는지 기록합니다. 대화를 지워도 기록은 남습니다.
      </p>

      <div style={{ display: 'flex', gap: 'var(--space-3)', marginBottom: 'var(--space-4)', flexWrap: 'wrap' }}>
        <select
          aria-label="근거 검증 결과"
          className="krds-form-select small"
          value={grounding}
          onChange={(e) => { setGrounding(e.target.value as Grounding | ''); setPage(0) }}
        >
          <option value="">근거 검증 전체</option>
          {Object.entries(GROUNDING_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
        <input
          aria-label="근거 문서 ID로 찾기"
          placeholder="문서 ID로 찾기(이 문서를 근거로 쓴 답변)"
          className="krds-input small"
          style={{ minWidth: 320 }}
          value={documentId}
          onChange={(e) => { setDocumentId(e.target.value); setPage(0) }}
        />
      </div>

      {isLoading && <Loader2 size={24} aria-label="불러오는 중" />}
      {isError && <p role="alert">답변 추적 기록을 불러오지 못했습니다.</p>}
      {!isLoading && !isError && items.length === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', ...muted }}>
          <Route size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
          <p>조건에 맞는 답변 기록이 없습니다.</p>
        </div>
      )}

      {items.length > 0 && (
        <div className="krds-table-wrap">
          <table className="tbl col data">
            <caption>답변 추적 목록</caption>
            <thead>
              <tr>
                <th scope="col">시각</th>
                <th scope="col">질문한 사람</th>
                <th scope="col">질문</th>
                <th scope="col">근거 검증</th>
                <th scope="col">근거·인용</th>
                <th scope="col">모델</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id} style={{ background: selected === t.id ? '#eff6ff' : undefined }}>
                  <td style={{ whiteSpace: 'nowrap', ...muted }}>{formatTime(t.created_at)}</td>
                  <td>
                    {t.username ?? '(삭제된 사용자)'}
                    {t.channel === 'mcp' && <> <span className="krds-badge xsmall bg-information">외부 에이전트</span></>}
                    {t.mode === 'deep' && <> <span className="krds-badge xsmall bg-secondary">심층 검색</span></>}
                  </td>
                  <td>
                    <button type="button" className="krds-btn text small" onClick={() => setSelected(t.id)}>
                      {t.query}
                    </button>
                  </td>
                  <td>
                    {t.status === 'FAILED' ? '생성 실패' : t.grounding ? GROUNDING_LABELS[t.grounding] : '-'}
                    {t.cache_hit ? ' · 캐시' : ''}
                  </td>
                  <td>{t.source_count}건 중 {t.cited_count}건 인용</td>
                  <td style={muted}>{t.model_key ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', gap: 'var(--space-3)', marginTop: 'var(--space-4)' }}>
          <button className="krds-btn small secondary" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>이전</button>
          <span style={{ ...muted, alignSelf: 'center' }}>{page + 1} / {totalPages}</span>
          <button className="krds-btn small secondary" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>다음</button>
        </div>
      )}

      {selected && <TraceDetail traceId={selected} onClose={() => setSelected(null)} />}
    </div>
  )
}
