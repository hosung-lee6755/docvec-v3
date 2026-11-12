import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Route, ShieldOff, X } from 'lucide-react'
import {
  useAnswerTrace,
  useAnswerTraces,
  type AnswerTraceItem,
  type AnswerTraceSource,
  type Grounding,
  type SourceAccess,
} from '../hooks/useAnswerTraces'
import { useAuthStore } from '../store/authStore'
import { SECURITY_LEVEL_LABELS } from '../hooks/useAccess'
import type { SecurityLevel } from '../hooks/useDocumentMetadata'
import { DeepSearchSteps } from '../components/chat/DeepSearch'
import { CitationEvidence, LowOcrBadge } from '../components/chat/CitationEvidence'
import {
  Alert, Badge, Button, DescriptionList, EmptyState, IconButton, Page, PageBody, PageHeader,
  SearchInput, Select, Spinner, Stat, StatStrip, Toolbar, Split,
} from '../components/ui'
import type { DescriptionItem } from '../components/ui'
import { roleLabel } from '../lib/roleLabels'

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


// 보안등급 값(Public 등)을 화면 글자(공개 등)로 바꾼다. 모르는 값은 그대로 보인다.
// 로컬 모델은 토큰 수를 기록하지 않는다. '- / -' 대신 그 사실을 적는다.
function formatTokens(input: number | null | undefined, output: number | null | undefined): string {
  if (input == null && output == null) return '토큰 기록 없음'
  return `입력 ${input ?? '-'} / 출력 ${output ?? '-'} 토큰`
}

function formatLatency(ms: number | null | undefined): string {
  if (ms == null) return '응답 시간 기록 없음'
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}초`
}

function levelLabel(level: string | null | undefined): string {
  if (!level) return '-'
  return SECURITY_LEVEL_LABELS[level as SecurityLevel] ?? level
}
function formatTime(value: string): string {
  return new Date(value).toLocaleString('ko-KR')
}

function rowClassName(item: AnswerTraceItem, isSelected: boolean): string | undefined {
  if (item.status === 'FAILED') return 'is-danger'
  if (item.grounding === 'failed') return isSelected ? 'is-selected' : 'is-warning'
  return isSelected ? 'is-selected' : undefined
}

function SourceCard({ source }: { source: AnswerTraceSource }) {
  const hiddenText =
    source.access === 'visible'
      ? '현재 본문을 찾을 수 없습니다(표 행·캐시 인용이거나 재처리로 청크가 바뀜).'
      : ACCESS_LABELS[source.access]
  return (
    <li style={{ border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', listStyle: 'none', background: 'var(--color-surface)' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--space-2)', alignItems: 'center', fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>
        <strong style={{ color: 'var(--color-text)' }}>[{source.rank}]</strong>
        {source.access === 'visible' ? (
          <>
            <span>{source.filename ?? '이름 없음'}</span>
            {source.page_number ? <span>{source.page_number}쪽</span> : null}
            <LowOcrBadge evidence={source.evidence} />
            <span>등급 {levelLabel(source.security_level)}</span>
          </>
        ) : (
          <span>문서 정보 비공개</span>
        )}
        <span>{source.cited ? '답변에 인용됨' : '인용 안 됨'}</span>
        <Badge tone={source.access === 'visible' ? 'success' : 'warning'} hasDot>{ACCESS_LABELS[source.access]}</Badge>
        {source.text_changed && <Badge tone="warning">답변 이후 문서가 바뀜</Badge>}
      </div>
      <p style={{ margin: 'var(--space-2) 0 0', fontSize: 'var(--text-sm)', lineHeight: 'var(--leading-normal)', whiteSpace: 'pre-wrap' }}>
        {source.text ?? <span className="ds-cell-muted">{hiddenText}</span>}
      </p>
      {source.access === 'visible' && <CitationEvidence evidence={source.evidence} />}
    </li>
  )
}

function buildFacts(data: NonNullable<ReturnType<typeof useAnswerTrace>['data']>): DescriptionItem[] {
  const rows: [string, string][] = [
    ['질문한 사람', `${data.username ?? '(삭제된 사용자)'} · 역할 ${roleLabel(data.user_role)} · 열람등급 ${levelLabel(data.clearance_level)}`],
    ['권한 맥락', `소속 그룹 ${data.group_ids.length}개 · 접근 가능 컬렉션 ${data.accessible_collection_count}개`],
    ['질문 방식', data.mode === 'deep' ? '심층 검색(하위 질문으로 나눠 찾은 뒤 종합)' : '일반'],
    ['질문 경로', data.channel === 'mcp' ? `외부 에이전트(토큰 ${data.access_token_id ?? '삭제됨'})` : '채팅 화면'],
    // 캐시 재사용이면 모델을 부르지 않았으므로 모델 칸이 비어 있다. 빈 칸 대신 그 사실을 적는다.
    ['모델', data.cache_hit ? '캐시 재사용(모델 호출 없음)' : `${data.model_key ?? '-'} (${data.provider ?? '-'}) · 검증 모델 ${data.verifier_model ?? '-'}`],
    ['근거 검증', `${data.grounding ? GROUNDING_LABELS[data.grounding] : '-'}${data.broadened ? ' · 재검색함' : ''}${data.cache_hit ? ' · 캐시 재사용' : ''}`],
    ['시스템 프롬프트', PROMPT_SOURCE_LABELS[data.system_prompt_source ?? ''] ?? '-'],
    ['토큰·응답 시간', `${formatTokens(data.input_tokens, data.output_tokens)} · ${formatLatency(data.latency_ms)}`],
  ]
  return rows.map(([term, detail]) => ({ key: term, term, detail }))
}

function TraceDetail({ traceId, onClose }: { traceId: string; onClose: () => void }) {
  const { data, isLoading, isError } = useAnswerTrace(traceId)
  if (isLoading) return <div style={{ padding: 'var(--space-4)' }}><Spinner /></div>
  if (isError || !data) return <Alert tone="danger">추적 기록을 불러오지 못했습니다.</Alert>

  return (
    <section aria-label="답변 추적 상세" className="ds-side-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 'var(--space-2)' }}>
        <div>
          <div className="ds-side-panel__eyebrow">{formatTime(data.created_at)}</div>
          <h2 className="ds-side-panel__title">답변 추적 상세</h2>
        </div>
        <IconButton label="상세 닫기" onClick={onClose}><X size={16} aria-hidden="true" /></IconButton>
      </div>
      <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)' }}>이 화면을 연 기록은 감사 로그에 남습니다.</p>

      <DescriptionList items={buildFacts(data)} />

      <div>
        <h3 className="ds-section-title" style={{ marginBottom: 'var(--space-1)' }}>질문</h3>
        <p style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 'var(--text-sm)' }}>{data.query}</p>
      </div>
      <div>
        <h3 className="ds-section-title" style={{ marginBottom: 'var(--space-1)' }}>
          답변 <Badge tone="info">AI가 생성한 답변</Badge>
        </h3>
        <p style={{ margin: 0, whiteSpace: 'pre-wrap', fontSize: 'var(--text-sm)' }}>{data.answer ?? data.error_message ?? '-'}</p>
      </div>

      {data.agent_steps && <DeepSearchSteps steps={data.agent_steps} defaultOpen />}

      <div>
        <h3 className="ds-section-title" style={{ marginBottom: 'var(--space-1)' }}>근거로 넣은 발췌문 ({data.sources.length})</h3>
        <p className="ds-cell-muted" style={{ margin: '0 0 var(--space-2)', fontSize: 'var(--text-xs)' }}>
          본문과 파일명은 지금 내가 볼 수 있는 문서만 보입니다. 관리자도 문서 열람 권한을 건너뛰지 않습니다.
        </p>
        <ul style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', padding: 0, margin: 0 }}>
          {data.sources.map((s) => <SourceCard key={s.rank} source={s} />)}
        </ul>
      </div>
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
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const items = data?.items ?? []
  const failedGroundingCount = items.filter((t) => t.grounding === 'failed').length
  const generationFailedCount = items.filter((t) => t.status === 'FAILED').length
  const uncitedCount = items.filter((t) => t.cited_count === 0).length

  const main = (
    <PageBody>
      {isLoading && <Spinner />}
      {isError && <Alert tone="danger">답변 추적 기록을 불러오지 못했습니다.</Alert>}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState icon={<Route size={48} aria-hidden="true" />} title="조건에 맞는 답변 기록이 없습니다." />
      )}

      {items.length > 0 && (
        <div className="ds-table-wrap">
          <table className="ds-table ds-table--compact">
            <caption className="sr-only">답변 추적 목록</caption>
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
                <tr key={t.id} className={rowClassName(t, selected === t.id)}>
                  <td className="ds-cell-muted" style={{ whiteSpace: 'nowrap' }}>{formatTime(t.created_at)}</td>
                  <td>
                    {t.username ?? '(삭제된 사용자)'}
                    {t.channel === 'mcp' && <> <Badge tone="info" isPlain>외부 에이전트</Badge></>}
                    {t.mode === 'deep' && <> <Badge tone="neutral" isPlain>심층 검색</Badge></>}
                  </td>
                  <td>
                    <button type="button" className="ds-link-btn" aria-pressed={selected === t.id} onClick={() => setSelected(t.id)}>{t.query}</button>
                  </td>
                  <td>
                    {t.status === 'FAILED'
                      ? '생성 실패'
                      : t.grounding ? GROUNDING_LABELS[t.grounding] : t.cache_hit ? '캐시 재사용' : '-'}
                    {t.cache_hit && t.grounding ? ' · 캐시' : ''}
                  </td>
                  <td>{t.source_count}건 중 {t.cited_count}건 인용</td>
                  <td className="ds-cell-muted">{t.cache_hit ? '캐시 재사용' : t.model_key ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {items.length > 0 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: 'var(--space-3)' }}>
          <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>이전</Button>
          <span className="ds-cell-muted" style={{ fontSize: 'var(--text-sm)' }}>{page + 1} / {totalPages}</span>
          <Button variant="secondary" size="sm" disabled={page + 1 >= totalPages} onClick={() => setPage((p) => p + 1)}>다음</Button>
        </div>
      )}
    </PageBody>
  )

  return (
    <Page>
      <PageHeader
        title="답변 추적"
        subtitle="채팅 답변마다 누가 어떤 권한으로 물었고 어떤 문서를 근거로 받았는지 기록합니다. 대화를 지워도 기록은 남습니다."
      />
      <StatStrip>
        <Stat label="전체 추적" value={(data?.total ?? 0).toLocaleString('ko-KR')} />
        <Stat label="이 페이지 생성 실패" value={generationFailedCount} tone={generationFailedCount > 0 ? 'danger' : 'default'} />
        <Stat label="이 페이지 근거 부족" value={failedGroundingCount} tone={failedGroundingCount > 0 ? 'warning' : 'default'} />
        <Stat label="이 페이지 인용 없는 답변" value={uncitedCount} tone={uncitedCount > 0 ? 'warning' : 'default'} />
      </StatStrip>

      <Toolbar label="답변 추적 거르기" meta={`${page + 1} / ${totalPages} 쪽`}>
        <Select
          controlSize="sm"
          aria-label="근거 검증 결과"
          value={grounding}
          onChange={(e) => { setGrounding(e.target.value as Grounding | ''); setPage(0) }}
        >
          <option value="">근거 검증 전체</option>
          {Object.entries(GROUNDING_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </Select>
        <SearchInput
          label="근거 문서 ID로 찾기"
          placeholder="문서 ID로 찾기(이 문서를 근거로 쓴 답변)"
          width={340}
          value={documentId}
          onChange={(e) => { setDocumentId(e.target.value); setPage(0) }}
        />
      </Toolbar>

      <Split
        main={main}
        panel={selected ? <TraceDetail key={selected} traceId={selected} onClose={() => setSelected(null)} /> : undefined}
      />
    </Page>
  )
}
