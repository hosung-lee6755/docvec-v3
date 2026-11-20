import { useState } from 'react'
import {
  useRegisterTraceGoldenQuery,
  useSetTraceReview,
  type AnswerTraceDetail,
  type ReviewCause,
} from '../../hooks/useAnswerTraces'
import { useCollections } from '../../hooks/useCollections'
import { useDocuments } from '../../hooks/useDocuments'
import { parseExpectedFacts } from '../../hooks/useGoldenQueries'
import { apiErrorDetail } from '../../lib/apiError'
import { Alert, Badge, Button, Field, Input, Select, Textarea } from '../ui'
import { REVIEW_CAUSE_LABELS } from './reviewCauses'

const DOCUMENT_LIMIT = 100

function defaultCollection(trace: AnswerTraceDetail): string {
  const fromSources = trace.sources.find((s) => s.access === 'visible' && s.collection_id)?.collection_id
  return trace.scope_collection_id ?? fromSources ?? ''
}

function CauseSelect({ trace }: { trace: AnswerTraceDetail }) {
  const setReview = useSetTraceReview(trace.id)
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      <Select
        controlSize="sm"
        aria-label="답변 문제의 원인"
        value={trace.review_cause ?? ''}
        disabled={setReview.isPending}
        onChange={(e) => setReview.mutate((e.target.value || null) as ReviewCause | null)}
      >
        <option value="">원인 표시 안 함</option>
        {Object.entries(REVIEW_CAUSE_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </Select>
      {trace.review_cause && trace.reviewed_at && (
        <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>
          {trace.reviewed_by_name ?? '(삭제된 사용자)'}님이 표시했습니다({new Date(trace.reviewed_at).toLocaleString('ko-KR')}).
        </span>
      )}
      {setReview.isError && <Alert tone="danger">{apiErrorDetail(setReview.error, '원인을 저장하지 못했습니다.')}</Alert>}
    </div>
  )
}

function ExpectedDocuments({ collectionId, sourceDocumentIds, selected, onToggle }: {
  collectionId: string
  sourceDocumentIds: Set<string>
  selected: Set<string>
  onToggle: (documentId: string) => void
}) {
  const { data } = useDocuments({ collectionId, limit: DOCUMENT_LIMIT })
  // 이번 답변의 근거로 쓰인 문서를 위에 둔다. 검색이 틀렸다면 정답 문서는 그 아래에 있다
  const documents = [...(data?.items ?? [])].sort(
    (a, b) => Number(sourceDocumentIds.has(b.id)) - Number(sourceDocumentIds.has(a.id)),
  )
  if (documents.length === 0) {
    return <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>이 컬렉션에 문서가 없습니다.</span>
  }
  return (
    <div style={{ maxHeight: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      {documents.map((d) => (
        <label key={d.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', fontSize: 'var(--text-sm)' }}>
          <input type="checkbox" checked={selected.has(d.id)} onChange={() => onToggle(d.id)} />
          {d.original_filename}
          {sourceDocumentIds.has(d.id) && <Badge tone="neutral" isPlain>이번 답변의 근거</Badge>}
        </label>
      ))}
    </div>
  )
}

function GoldenQueryForm({ trace, onCancel }: { trace: AnswerTraceDetail; onCancel: () => void }) {
  const register = useRegisterTraceGoldenQuery(trace.id)
  const { data: collections } = useCollections()
  const [collectionId, setCollectionId] = useState(() => defaultCollection(trace))
  const [query, setQuery] = useState(trace.query)
  const [expected, setExpected] = useState<Set<string>>(new Set())
  const [facts, setFacts] = useState('')
  const sourceDocumentIds = new Set(
    trace.sources.filter((s) => s.access === 'visible' && s.document_id).map((s) => s.document_id as string),
  )
  const canSubmit = !!collectionId && !!query.trim() && expected.size > 0 && !register.isPending

  const toggle = (documentId: string) =>
    setExpected((prev) => {
      const next = new Set(prev)
      if (next.has(documentId)) next.delete(documentId)
      else next.add(documentId)
      return next
    })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    register.mutate(
      {
        collection_id: collectionId,
        query: query.trim(),
        expected_document_ids: Array.from(expected),
        expected_facts: parseExpectedFacts(facts),
      },
      { onSuccess: onCancel },
    )
  }

  return (
    <form onSubmit={handleSubmit} className="trace-review__form">
      <Select
        controlSize="sm"
        aria-label="골든 쿼리를 넣을 컬렉션"
        value={collectionId}
        onChange={(e) => {
          setCollectionId(e.target.value)
          setExpected(new Set())
        }}
      >
        <option value="">컬렉션 선택</option>
        {(collections?.items ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </Select>
      <Input
        type="text"
        controlSize="sm"
        aria-label="골든 쿼리 질문"
        value={query}
        maxLength={1000}
        onChange={(e) => setQuery(e.target.value)}
      />
      <div className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)' }}>
        이 질문에 나와야 하는 문서를 고르세요. 이번 답변의 근거로 쓰인 문서에는 표시가 붙습니다.
      </div>
      {collectionId && (
        <ExpectedDocuments
          collectionId={collectionId}
          sourceDocumentIds={sourceDocumentIds}
          selected={expected}
          onToggle={toggle}
        />
      )}
      <Field label="기대 사실 (선택, 한 줄에 하나)" hint="답에 그대로 나와야 하는 숫자, 날짜, 이름을 적습니다.">
        {(id) => <Textarea id={id} rows={2} value={facts} onChange={(e) => setFacts(e.target.value)} />}
      </Field>
      <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
        <Button type="submit" size="sm" variant="primary" disabled={!canSubmit}>등록</Button>
        <Button type="button" size="sm" variant="secondary" onClick={onCancel}>취소</Button>
      </div>
      {register.isError && <Alert tone="danger">{apiErrorDetail(register.error, '골든 쿼리로 등록하지 못했습니다.')}</Alert>}
    </form>
  )
}

function GoldenQueryStatus({ trace }: { trace: AnswerTraceDetail }) {
  const { data: collections } = useCollections()
  const [isOpen, setIsOpen] = useState(false)

  if (trace.golden_query_id) {
    const name = collections?.items.find((c) => c.id === trace.golden_query_collection_id)?.name ?? '알 수 없는'
    return (
      <p style={{ margin: 0, fontSize: 'var(--text-sm)' }}>
        <Badge tone="success" hasDot>회귀 점검 중</Badge>{' '}
        '{name}' 컬렉션의 골든 쿼리로 등록했습니다. 컬렉션 화면의 골든 쿼리 평가에서 고치거나 지울 수 있습니다.
      </p>
    )
  }
  if (!isOpen) {
    return (
      <div>
        <Button size="sm" variant="secondary" onClick={() => setIsOpen(true)}>골든 쿼리로 등록</Button>
      </div>
    )
  }
  return <GoldenQueryForm trace={trace} onCancel={() => setIsOpen(false)} />
}

// 답변 추적 상세의 개선 조치(2026-11-20). 관리자가 문제 원인을 표시하고, 질문을 골든 쿼리로 등록해 회귀 점검에 넣는다.
export function TraceReview({ trace }: { trace: AnswerTraceDetail }) {
  return (
    <section aria-label="개선 조치" className="trace-review">
      <h3 className="ds-section-title" style={{ margin: 0 }}>개선 조치</h3>
      <p className="ds-cell-muted" style={{ margin: 0, fontSize: 'var(--text-xs)' }}>
        원인을 표시해 두면 목록에서 원인별로 모아 볼 수 있습니다. 골든 쿼리로 등록하면 이 질문이 평가 때마다 다시 점검됩니다.
      </p>
      <CauseSelect trace={trace} />
      <GoldenQueryStatus trace={trace} />
    </section>
  )
}
