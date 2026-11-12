import { useMemo, useRef, useState, type ChangeEvent, type FormEvent, type ReactNode } from 'react'
import {
  ArrowLeftRight, Ban, BookOpen, Download,
  History, Loader2, Pencil, ShieldOff, Tag, Trash2, Upload, X,
} from 'lucide-react'
import {
  useCreateDictionaryEntry,
  useDeleteDictionaryEntry,
  useDictionaryEntries,
  useDictionaryEntryImpact,
  useExportDictionaryEntries,
  useImportDictionaryEntries,
  useUpdateDictionaryEntry,
  type DictionaryEntry,
  type DictionaryEntryInput,
  type DictionaryEntryType,
  type DictionaryImpact,
  type DictionaryImportResult,
  type MatchType,
  type SynonymDirection,
  type SynonymProcessingMode,
  type UserProcessingRule,
  type UserTermType,
} from '../hooks/useDictionary'
import { useAuthStore } from '../store/authStore'
import { ImpactModal } from '../components/dictionary/ImpactModal'
import { RevisionView } from '../components/dictionary/RevisionView'
import {
  Alert, Button, Card, EmptyState, Field, IconButton, Input, Page, PageHeader, Select, SearchInput, Tabs, Toolbar,
} from '../components/ui'
import '../styles/screens/pipeline.css'

const TABS: { type: DictionaryEntryType; label: string; hint: string; icon: typeof Ban }[] = [
  { type: 'stopword', label: '불용어', hint: '분석/검색에서 의미 기여도가 낮아 제외할 단어입니다.', icon: Ban },
  { type: 'synonym', label: '동의어', hint: '여러 표현을 하나의 대표 용어로 통합하거나 검색 시 함께 확장합니다.', icon: ArrowLeftRight },
  { type: 'custom_word', label: '사용자 사전', hint: '전문용어·기관명·제품명 등 도메인 용어의 인식/치환/태깅 규칙을 관리합니다.', icon: Tag },
]

const MATCH_TYPE_LABELS: Record<MatchType, string> = {
  EXACT: '정확히 일치', CONTAINS: '포함', PREFIX: '시작 문자열', SUFFIX: '끝 문자열', REGEX: '정규식',
}
const DIRECTION_LABELS: Record<SynonymDirection, string> = {
  ONE_WAY: '단방향 (동의어 → 대표어)', BIDIRECTIONAL: '양방향',
}
const PROCESSING_MODE_LABELS: Record<SynonymProcessingMode, string> = {
  NORMALIZE: '정규화 (검색 시 대표어로 통합)', REPLACE: '치환 (문서 텍스트 변경)',
  SEARCH_EXPAND: '검색 확장', TAGGING: '태깅',
}
const TERM_TYPE_LABELS: Record<UserTermType, string> = {
  TECHNICAL_TERM: '전문용어', ABBREVIATION: '약어', ORGANIZATION: '기관명', PERSON: '인명',
  PRODUCT: '제품/서비스명', PROJECT: '프로젝트명', POLICY: '정책/제도명', CUSTOM: '기타',
}
const PROCESSING_RULE_LABELS: Record<UserProcessingRule, string> = {
  KEEP: '원문 유지', NORMALIZE: '표준어로 정규화', REPLACE: '치환', TAG: '태그 부여',
  EXTRACT: '주요 개체 추출', MASK: '민감정보 마스킹', IGNORE: '처리 대상에서 제외',
}

interface FormState {
  term: string
  variants: string[]
  matchType: MatchType
  direction: SynonymDirection
  processingMode: SynonymProcessingMode
  termType: UserTermType
  processingRule: UserProcessingRule
  pronunciation: string
  caseSensitive: boolean
  language: string
  scope: string
  description: string
  enabled: boolean
}

const EMPTY_FORM: FormState = {
  term: '', variants: [], matchType: 'EXACT', direction: 'ONE_WAY', processingMode: 'NORMALIZE',
  termType: 'CUSTOM', processingRule: 'KEEP', pronunciation: '', caseSensitive: false,
  language: 'ko', scope: 'ALL', description: '', enabled: true,
}

type ImportFeedback = { ok: true; result: DictionaryImportResult } | { ok: false; message: string }

function ChipInput({ id, values, onChange, placeholder }: {
  id?: string; values: string[]; onChange: (next: string[]) => void; placeholder: string
}) {
  const [draft, setDraft] = useState('')

  function commit() {
    const v = draft.trim()
    if (!v || values.includes(v)) { setDraft(''); return }
    onChange([...values, v])
    setDraft('')
  }

  return (
    <div>
      {values.length > 0 && (
        <div className="pipeline-chip-row" style={{ marginBottom: 6 }}>
          {values.map((v) => (
            <span key={v} className="pipeline-chip">
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((variant) => variant !== v))}
                aria-label={`${v} 제거`}
                className="pipeline-chip__remove"
              >
                <X size={11} aria-hidden="true" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <Input
          id={id}
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } }}
          placeholder={placeholder}
          controlSize="sm"
          style={{ flex: 1, minWidth: 0 }}
        />
        <Button variant="secondary" size="sm" onClick={commit}>추가</Button>
      </div>
    </div>
  )
}

function chipsCell(values: string[]): ReactNode {
  if (!values.length) return <span className="ds-cell-muted">-</span>
  return (
    <div className="pipeline-chip-row">
      {values.map((v) => <span key={v} className="pipeline-chip">{v}</span>)}
    </div>
  )
}

function mutedOrDash(text: string | null | undefined): ReactNode {
  return text || <span className="ds-cell-muted">-</span>
}

type Column = { header: string; width?: string; render: (e: DictionaryEntry) => ReactNode }

const COLUMNS: Record<DictionaryEntryType, Column[]> = {
  stopword: [
    { header: '단어', render: (e) => <strong>{e.term}</strong> },
    { header: '일치방식', render: (e) => MATCH_TYPE_LABELS[e.match_type ?? 'EXACT'] },
    { header: '언어', width: '8%', render: (e) => e.language },
    { header: '적용범위', render: (e) => e.scope.join(', ') },
    { header: '제외사유', render: (e) => mutedOrDash(e.description) },
  ],
  synonym: [
    { header: '대표용어', render: (e) => <strong>{e.term}</strong> },
    { header: '동의어', render: (e) => chipsCell(e.variants) },
    { header: '적용방향', render: (e) => DIRECTION_LABELS[e.direction ?? 'ONE_WAY'] },
    { header: '처리방식', render: (e) => PROCESSING_MODE_LABELS[e.processing_mode ?? 'NORMALIZE'] },
    { header: '적용범위', render: (e) => e.scope.join(', ') },
  ],
  custom_word: [
    { header: '표준용어', render: (e) => <strong>{e.term}</strong> },
    { header: '변형표현', render: (e) => chipsCell(e.variants) },
    { header: '용어유형', render: (e) => TERM_TYPE_LABELS[e.term_type ?? 'CUSTOM'] },
    { header: '처리규칙', render: (e) => PROCESSING_RULE_LABELS[e.processing_rule ?? 'KEEP'] },
    { header: '정의', render: (e) => mutedOrDash(e.description) },
  ],
}

export default function DictionaryPage() {
  const currentUser = useAuthStore((s) => s.user)
  const [view, setView] = useState<'entries' | 'revisions'>('entries')
  const [tab, setTab] = useState<DictionaryEntryType>('stopword')
  const [form, setForm] = useState<FormState>(EMPTY_FORM)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [filter, setFilter] = useState('')
  const [importFeedback, setImportFeedback] = useState<ImportFeedback | null>(null)
  const [impact, setImpact] = useState<DictionaryImpact | null>(null)
  const [reprocessDone, setReprocessDone] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const { data, isLoading, isError } = useDictionaryEntries(tab)
  const createEntry = useCreateDictionaryEntry(tab)
  const updateEntry = useUpdateDictionaryEntry(tab)
  const deleteEntry = useDeleteDictionaryEntry(tab)
  const exportEntries = useExportDictionaryEntries(tab)
  const importEntries = useImportDictionaryEntries(tab)
  const entryImpact = useDictionaryEntryImpact()

  const filtered = useMemo(() => {
    const items = data?.items ?? []
    const q = filter.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (entry) =>
        entry.term.toLowerCase().includes(q) ||
        entry.variants.some((v) => v.toLowerCase().includes(q)) ||
        (entry.description ?? '').toLowerCase().includes(q),
    )
  }, [data, filter])

  if (currentUser?.role !== 'admin') {
    return (
      <Page>
        <EmptyState icon={<ShieldOff size={48} aria-hidden="true" />} title="관리자만 접근할 수 있습니다." />
      </Page>
    )
  }

  const activeTab = TABS.find((t) => t.type === tab)
  if (!activeTab) {
    return (
      <Page>
        <EmptyState title="탭 정보를 찾을 수 없습니다." />
      </Page>
    )
  }

  function resetForm() {
    setForm(EMPTY_FORM)
    setEditingId(null)
  }

  function switchTab(next: DictionaryEntryType) {
    setTab(next)
    setFilter('')
    setImportFeedback(null)
    resetForm()
  }

  function startEdit(entry: DictionaryEntry) {
    setEditingId(entry.id)
    setForm({
      term: entry.term,
      variants: entry.variants,
      matchType: entry.match_type ?? 'EXACT',
      direction: entry.direction ?? 'ONE_WAY',
      processingMode: entry.processing_mode ?? 'NORMALIZE',
      termType: entry.term_type ?? 'CUSTOM',
      processingRule: entry.processing_rule ?? 'KEEP',
      pronunciation: entry.pronunciation ?? '',
      caseSensitive: entry.case_sensitive,
      language: entry.language,
      scope: entry.scope.join(', '),
      description: entry.description ?? '',
      enabled: entry.enabled,
    })
  }

  function toggleEnabled(entry: DictionaryEntry) {
    updateEntry.mutate({ id: entry.id, enabled: !entry.enabled })
  }

  function buildPayload(): DictionaryEntryInput {
    const scope = form.scope.split(',').map((s) => s.trim()).filter(Boolean)
    const base = {
      term: form.term.trim(),
      case_sensitive: form.caseSensitive,
      language: form.language.trim() || 'ko',
      scope: scope.length ? scope : ['ALL'],
      description: form.description.trim() || undefined,
      enabled: form.enabled,
    }
    if (tab === 'stopword') return { ...base, match_type: form.matchType }
    if (tab === 'synonym') {
      return { ...base, variants: form.variants, direction: form.direction, processing_mode: form.processingMode }
    }
    return {
      ...base, variants: form.variants, term_type: form.termType, processing_rule: form.processingRule,
      pronunciation: form.pronunciation.trim() || undefined,
    }
  }

  function checkImpact(entry: DictionaryEntry) {
    setReprocessDone(null)
    entryImpact.mutate(entry.id, {
      onSuccess: (result) => {
        if (result.affected_document_count > 0) setImpact(result)
      },
    })
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (!form.term.trim()) return
    if (tab === 'synonym' && form.variants.length === 0) return
    const payload = buildPayload()
    if (editingId) {
      updateEntry.mutate(
        { id: editingId, ...payload },
        { onSuccess: (saved) => { resetForm(); checkImpact(saved) } },
      )
    } else {
      createEntry.mutate(payload, { onSuccess: resetForm })
    }
  }

  function handleImportFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    importEntries.mutate(file, {
      onSuccess: (result) => setImportFeedback({ ok: true, result }),
      onError: (err: unknown) => {
        const message =
          (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
          ?? '엑셀 파일을 가져오지 못했습니다.'
        setImportFeedback({ ok: false, message })
      },
    })
  }

  const isSaving = createEntry.isPending || updateEntry.isPending
  const columns = COLUMNS[tab]
  const entryCount = data?.items.length ?? 0
  const enabledCount = data?.items.filter((e) => e.enabled).length ?? 0
  const termField = tab === 'stopword' ? '단어' : tab === 'synonym' ? '대표 용어' : '표준 용어'
  const descriptionField = tab === 'stopword' ? '제외 사유' : tab === 'synonym' ? '설명' : '정의'

  const viewTabs = [
    { value: 'entries' as const, label: '사전 항목' },
    { value: 'revisions' as const, label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><History size={13} aria-hidden="true" />버전 이력</span> },
  ]
  const typeTabs = TABS.map((t) => {
    const Icon = t.icon
    return {
      value: t.type,
      label: <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Icon size={14} aria-hidden="true" />{t.label}</span>,
    }
  })

  return (
    <Page>
      <PageHeader
        title="검색 사전 관리"
        subtitle="BM25 키워드 검색(하이브리드 모드)에 사용되는 한국어 형태소 분석기(kiwipiepy) 기반 불용어/동의어/사용자 사전을 관리합니다. 저장 즉시 검색에 반영됩니다. 단, 문서 원문 치환(REPLACE)·태깅(TAG/TAGGING)·개체 추출(EXTRACT)·마스킹(MASK) 규칙은 현재 값으로 저장은 되지만 검색 토큰화 단계에는 아직 적용되지 않으며, 실제 검색에는 KEEP/NORMALIZE(정규화)만 동작합니다."
      />

      <Tabs
        items={viewTabs}
        value={view}
        onChange={setView}
        label="사전 보기 전환"
        idPrefix="dict-view"
      />

      <div
        role="tabpanel"
        id="dict-view-panel-entries"
        aria-labelledby="dict-view-tab-entries"
        hidden={view !== 'entries'}
      >
        {view === 'entries' && (
          <>
            <Tabs
              items={typeTabs}
              value={tab}
              onChange={switchTab}
              label="사전 종류"
              idPrefix="dict-type"
            />

            <div
              role="tabpanel"
              id={`dict-type-panel-${tab}`}
              aria-labelledby={`dict-type-tab-${tab}`}
              className="dict-layout"
            >
              <Card title={editingId ? `${activeTab.label} 수정` : `${activeTab.label} 추가`} actions={editingId && (
                <Button variant="ghost" size="sm" onClick={resetForm}>취소</Button>
              )}>
                <p className="wf-muted" style={{ marginBottom: 'var(--space-4)' }}>{activeTab.hint}</p>

                <form onSubmit={handleSubmit} className="dict-form">
                  <Field label={termField}>
                    {(id) => (
                      <Input
                        id={id}
                        type="text"
                        value={form.term}
                        onChange={(e) => setForm({ ...form, term: e.target.value })}
                        placeholder="예: 검토"
                      />
                    )}
                  </Field>

                  {tab === 'stopword' && (
                    <Field label="일치 방식">
                      {(id) => (
                        <Select
                          id={id}
                          value={form.matchType}
                          onChange={(e) => setForm({ ...form, matchType: e.target.value as MatchType })}
                        >
                          {Object.entries(MATCH_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                        </Select>
                      )}
                    </Field>
                  )}

                  {tab === 'synonym' && (
                    <>
                      <Field label="동의어 (Enter로 추가)">
                        {(id) => (
                          <ChipInput
                            id={id}
                            values={form.variants}
                            onChange={(variants) => setForm({ ...form, variants })}
                            placeholder="예: AI"
                          />
                        )}
                      </Field>
                      <Field label="적용 방향">
                        {(id) => (
                          <Select
                            id={id}
                            value={form.direction}
                            onChange={(e) => setForm({ ...form, direction: e.target.value as SynonymDirection })}
                          >
                            {Object.entries(DIRECTION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </Select>
                        )}
                      </Field>
                      <Field label="처리 방식">
                        {(id) => (
                          <Select
                            id={id}
                            value={form.processingMode}
                            onChange={(e) => setForm({ ...form, processingMode: e.target.value as SynonymProcessingMode })}
                          >
                            {Object.entries(PROCESSING_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </Select>
                        )}
                      </Field>
                    </>
                  )}

                  {tab === 'custom_word' && (
                    <>
                      <Field label="변형 표현 (오탈자/별칭, Enter로 추가)">
                        {(id) => (
                          <ChipInput
                            id={id}
                            values={form.variants}
                            onChange={(variants) => setForm({ ...form, variants })}
                            placeholder="예: 랭그래프"
                          />
                        )}
                      </Field>
                      <Field label="용어 유형">
                        {(id) => (
                          <Select
                            id={id}
                            value={form.termType}
                            onChange={(e) => setForm({ ...form, termType: e.target.value as UserTermType })}
                          >
                            {Object.entries(TERM_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </Select>
                        )}
                      </Field>
                      <Field label="처리 규칙">
                        {(id) => (
                          <Select
                            id={id}
                            value={form.processingRule}
                            onChange={(e) => setForm({ ...form, processingRule: e.target.value as UserProcessingRule })}
                          >
                            {Object.entries(PROCESSING_RULE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                          </Select>
                        )}
                      </Field>
                      <Field label="발음">
                        {(id) => (
                          <Input
                            id={id}
                            type="text"
                            value={form.pronunciation}
                            onChange={(e) => setForm({ ...form, pronunciation: e.target.value })}
                            placeholder="예: 랭그래프"
                          />
                        )}
                      </Field>
                    </>
                  )}

                  <Field label={descriptionField}>
                    {(id) => (
                      <Input
                        id={id}
                        type="text"
                        value={form.description}
                        onChange={(e) => setForm({ ...form, description: e.target.value })}
                        placeholder="선택 입력"
                      />
                    )}
                  </Field>

                  <div className="dict-form-row">
                    <Field label="언어" className="pipeline-field-grow">
                      {(id) => (
                        <Input
                          id={id}
                          type="text"
                          value={form.language}
                          onChange={(e) => setForm({ ...form, language: e.target.value })}
                          placeholder="예: ko, en, all"
                        />
                      )}
                    </Field>
                    <Field label="적용 범위 (쉼표로 구분)" className="pipeline-field-grow">
                      {(id) => (
                        <Input
                          id={id}
                          type="text"
                          value={form.scope}
                          onChange={(e) => setForm({ ...form, scope: e.target.value })}
                          placeholder="ALL"
                        />
                      )}
                    </Field>
                  </div>

                  <div className="dict-form-row">
                    <label className="block-panel__check">
                      <input
                        id="dict_case_sensitive_chk"
                        type="checkbox"
                        checked={form.caseSensitive}
                        onChange={(e) => setForm({ ...form, caseSensitive: e.target.checked })}
                      />
                      대소문자 구분
                    </label>
                    <label className="block-panel__check">
                      <input
                        id="dict_enabled_chk"
                        type="checkbox"
                        checked={form.enabled}
                        onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                      />
                      사용여부
                    </label>
                  </div>

                  <Button
                    type="submit"
                    variant="primary"
                    isBlock
                    disabled={isSaving || !form.term.trim() || (tab === 'synonym' && form.variants.length === 0)}
                  >
                    {isSaving ? '저장 중…' : editingId ? '수정 완료' : '추가'}
                  </Button>
                </form>

                <div className="dict-io">
                  <p className="dict-io__title">엑셀로 일괄 관리</p>
                  <div className="dict-form-row">
                    <Button
                      variant="secondary"
                      isBlock
                      onClick={() => exportEntries.mutate()}
                      disabled={exportEntries.isPending}
                      icon={exportEntries.isPending
                        ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
                        : <Download size={14} aria-hidden="true" />}
                    >
                      다운로드
                    </Button>
                    {exportEntries.isError && (
                      <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)', color: 'var(--color-danger)', alignSelf: 'center' }}>
                        다운로드 실패
                      </span>
                    )}
                    <Button
                      variant="secondary"
                      isBlock
                      onClick={() => fileInputRef.current?.click()}
                      disabled={importEntries.isPending}
                      icon={importEntries.isPending
                        ? <Loader2 size={14} className="pipeline-spin" aria-hidden="true" />
                        : <Upload size={14} aria-hidden="true" />}
                    >
                      업로드
                    </Button>
                    <input ref={fileInputRef} type="file" accept=".xlsx" onChange={handleImportFile} style={{ display: 'none' }} />
                  </div>
                  <p className="wf-muted" style={{ marginTop: 'var(--space-2)' }}>
                    {tab === 'stopword' && '단어 | 일치방식 | 대소문자구분(Y/N) | 언어 | 적용범위 | 제외사유 | 사용여부(Y/N)'}
                    {tab === 'synonym' && '대표용어 | 동의어(;로 구분) | 적용방향 | 처리방식 | 대소문자구분 | 언어 | 적용범위 | 사용여부'}
                    {tab === 'custom_word' && '표준용어 | 변형표현(;로 구분) | 용어유형 | 처리규칙 | 정의 | 대소문자구분 | 언어 | 적용범위 | 사용여부 | 발음'}
                    {' '}순서 열을 수정한 뒤 그대로 업로드하면 같은 용어는 갱신, 새 용어는 추가됩니다.
                  </p>

                  {importFeedback && (
                    <div style={{ marginTop: 'var(--space-3)' }}>
                      <Alert tone={importFeedback.ok ? 'success' : 'danger'}>
                        {importFeedback.ok ? (
                          <span>
                            추가 {importFeedback.result.created}건, 수정 {importFeedback.result.updated}건
                            {importFeedback.result.skipped > 0 && `, 건너뜀 ${importFeedback.result.skipped}건 (행 ${importFeedback.result.skipped_rows.join(', ')})`}
                          </span>
                        ) : (
                          <span>{importFeedback.message}</span>
                        )}
                      </Alert>
                    </div>
                  )}
                </div>
              </Card>

              <Card
                title={(
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                    저장된 사전 미리보기
                    <span className="ds-cell-muted" style={{ fontSize: 'var(--text-xs)', fontWeight: 'var(--weight-regular)' }}>
                      {entryCount}건{entryCount > 0 && ` (사용중 ${enabledCount})`}
                    </span>
                  </span>
                )}
                isFlush
              >
                <Toolbar
                  label="사전 항목 거르기"
                  meta={`${filtered.length}건 표시`}
                >
                  <SearchInput
                    label="용어/동의어/설명 검색"
                    width={300}
                    value={filter}
                    onChange={(e) => setFilter(e.target.value)}
                    placeholder="용어/동의어/설명 검색"
                  />
                </Toolbar>

                {isLoading && (
                  <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
                    <Loader2 size={24} className="pipeline-spin" style={{ color: 'var(--color-text-muted)' }} aria-label="불러오는 중" />
                  </div>
                )}

                {isError && (
                  <div style={{ padding: 'var(--space-4)' }}>
                    <Alert tone="danger">사전 항목을 불러오지 못했습니다.</Alert>
                  </div>
                )}

                {!isLoading && !isError && filtered.length === 0 && (
                  <EmptyState
                    icon={<BookOpen size={40} aria-hidden="true" />}
                    title={filter ? '검색 결과가 없습니다.' : '등록된 항목이 없습니다.'}
                  />
                )}

                {!isLoading && !isError && filtered.length > 0 && (
                  <div className="ds-table-wrap">
                    <table className="ds-table">
                      <caption className="sr-only">{activeTab.label} 목록</caption>
                      <thead>
                        <tr>
                          {columns.map((col) => (
                            <th key={col.header} scope="col" style={col.width ? { width: col.width } : undefined}>
                              {col.header}
                            </th>
                          ))}
                          <th scope="col" style={{ width: '9%' }}>사용여부</th>
                          <th scope="col" style={{ width: '10%' }} aria-label="관리" />
                        </tr>
                      </thead>
                      <tbody>
                        {filtered.map((entry) => (
                          <tr key={entry.id} className={entry.enabled ? undefined : 'is-warning'}>
                            {columns.map((col) => (
                              <td key={col.header}>{col.render(entry)}</td>
                            ))}
                            <td>
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => toggleEnabled(entry)}
                                aria-pressed={entry.enabled}
                                style={{ color: entry.enabled ? 'var(--color-success)' : 'var(--color-text-muted)' }}
                              >
                                {entry.enabled ? '사용중' : '비활성'}
                              </Button>
                            </td>
                            <td>
                              <div style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                                <IconButton label={`${entry.term} 수정`} onClick={() => startEdit(entry)}>
                                  <Pencil size={12} aria-hidden="true" />
                                </IconButton>
                                <IconButton
                                  label={`${entry.term} 삭제`}
                                  tone="danger"
                                  onClick={() => deleteEntry.mutate(entry.id)}
                                >
                                  <Trash2 size={12} aria-hidden="true" />
                                </IconButton>
                              </div>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            </div>
          </>
        )}
      </div>

      <div
        role="tabpanel"
        id="dict-view-panel-revisions"
        aria-labelledby="dict-view-tab-revisions"
        hidden={view !== 'revisions'}
        style={{ padding: 'var(--space-4) var(--space-5)' }}
      >
        {view === 'revisions' && <RevisionView />}
      </div>

      <ImpactModal
        impact={impact}
        tab={tab}
        reprocessDone={reprocessDone}
        onClose={() => setImpact(null)}
        onReprocessDone={setReprocessDone}
      />
    </Page>
  )
}
