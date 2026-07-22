import { useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import {
  AlertTriangle, ArrowLeftRight, Ban, BookOpen, CheckCircle2, Clock, Download,
  History, Loader2, Pencil, Search, ShieldOff, Tag, Trash2, Upload, X,
} from 'lucide-react'
import {
  useCreateDictionaryEntry,
  useDeleteDictionaryEntry,
  useDictionaryEntries,
  useDictionaryEntryImpact,
  useDictionaryRevisions,
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
import { useStartPartialReprocess } from '../hooks/useDocumentRuns'
import { useAuthStore } from '../store/authStore'

const REVISION_CHANGE_LABELS: Record<string, string> = {
  CREATE: '추가', UPDATE: '수정', DELETE: '삭제', IMPORT: '엑셀 가져오기',
}

// DictionaryEntryType(백엔드/프론트 공용)을 부분 재처리 API의 start_block_type으로
// 매핑 — 사전 블록 3종의 실제 block_type 이름(stopword/synonym/user_dict)과
// entry_type 이름이 custom_word 하나만 다르다.
const ENTRY_TYPE_TO_BLOCK_TYPE: Record<DictionaryEntryType, string> = {
  stopword: 'stopword', synonym: 'synonym', custom_word: 'user_dict',
}

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

const chipStyle: CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 11,
  background: 'rgba(99,102,241,0.1)', color: 'var(--color-accent)',
  borderRadius: 999, padding: '2px 8px', whiteSpace: 'nowrap',
}

function ChipInput({ values, onChange, placeholder }: {
  values: string[]; onChange: (next: string[]) => void; placeholder: string
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
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 6 }}>
          {values.map((v) => (
            <span key={v} style={chipStyle}>
              {v}
              <button
                type="button"
                onClick={() => onChange(values.filter((variant) => variant !== v))}
                aria-label={`${v} 제거`}
                style={{ display: 'flex', color: 'inherit', opacity: 0.7 }}
              >
                <X size={11} />
              </button>
            </span>
          ))}
        </div>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); commit() } }}
          placeholder={placeholder}
          className="krds-input small"
          style={{ flex: 1 }}
        />
        <button type="button" onClick={commit} className="krds-btn medium secondary">추가</button>
      </div>
    </div>
  )
}

function chipsCell(values: string[]): ReactNode {
  if (!values.length) return <span style={{ color: 'var(--color-text-muted)' }}>-</span>
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
      {values.map((v) => <span key={v} style={chipStyle}>{v}</span>)}
    </div>
  )
}

type Column = { header: string; width?: string; render: (e: DictionaryEntry) => ReactNode }

const COLUMNS: Record<DictionaryEntryType, Column[]> = {
  stopword: [
    { header: '단어', render: (e) => <strong>{e.term}</strong> },
    { header: '일치방식', render: (e) => MATCH_TYPE_LABELS[e.match_type ?? 'EXACT'] },
    { header: '언어', width: '8%', render: (e) => e.language },
    { header: '적용범위', render: (e) => e.scope.join(', ') },
    { header: '제외사유', render: (e) => e.description || <span style={{ color: 'var(--color-text-muted)' }}>-</span> },
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
    { header: '정의', render: (e) => e.description || <span style={{ color: 'var(--color-text-muted)' }}>-</span> },
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
  const startPartialReprocess = useStartPartialReprocess()
  const { data: revisionsData, isLoading: revisionsLoading } = useDictionaryRevisions(view === 'revisions')

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
      <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
        <ShieldOff size={48} style={{ margin: '0 auto var(--space-4)', display: 'block', opacity: 0.4 }} />
        <p>관리자만 접근할 수 있습니다.</p>
      </div>
    )
  }

  const activeTab = TABS.find((t) => t.type === tab)!

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

  function handleSubmit(e: React.FormEvent) {
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

  async function handleReprocessAffected() {
    if (!impact) return
    const blockType = ENTRY_TYPE_TO_BLOCK_TYPE[tab]
    let done = 0
    for (const doc of impact.documents) {
      try {
        await startPartialReprocess.mutateAsync({
          documentId: doc.id,
          startBlockType: blockType,
          reason: '사전 항목 변경에 따른 일괄 재처리',
        })
        done += 1
      } catch {
        // 개별 문서 재처리 실패는 건너뛰고 나머지는 계속 진행 — 완료 건수에만 반영
      }
    }
    setReprocessDone(done)
  }

  function handleImportFile(e: React.ChangeEvent<HTMLInputElement>) {
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

  return (
    <div>
      <style>{`
        @keyframes dict-spin { to { transform: rotate(360deg) } }
        .dict-tab { position: relative; border-bottom: 2px solid transparent; transition: color var(--duration-fast), background var(--duration-fast); }
        .dict-tab:hover { background: rgba(29,78,216,0.08); }
        .dict-tab.active { border-bottom-color: #1d4ed8; }
        .dict-card { background: #fff; border: 1px solid var(--color-border); border-radius: var(--radius-lg); box-shadow: 0 1px 2px rgba(15,23,42,0.06); }
        .dict-row:hover { background: rgba(99,102,241,0.06); }
        .dict-layout { display: grid; grid-template-columns: 380px 1fr; gap: var(--space-6); align-items: start; }
        @media (max-width: 960px) { .dict-layout { grid-template-columns: 1fr; } }
        .dict-field { display: flex; flex-direction: column; gap: 4px; margin-bottom: var(--space-3); }
        .dict-field label { font-size: 12px; font-weight: 600; color: var(--color-text-muted); }
        .dict-toggle { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; }
      `}</style>

      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-2)' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>검색 사전 관리</h1>
      </div>

      <p style={{ color: 'var(--color-text-muted)', marginBottom: 'var(--space-6)', fontSize: 13, maxWidth: 760 }}>
        BM25 키워드 검색(하이브리드 모드)에 사용되는 한국어 형태소 분석기(kiwipiepy) 기반 불용어/동의어/사용자 사전을
        관리합니다. 저장 즉시 검색에 반영됩니다. 단, 문서 원문 치환(REPLACE)·태깅(TAG/TAGGING)·개체 추출(EXTRACT)·마스킹(MASK)
        규칙은 현재 값으로 저장은 되지만 검색 토큰화 단계에는 아직 적용되지 않으며, 실제 검색에는 KEEP/NORMALIZE(정규화)만
        동작합니다.
      </p>

      <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        <button
          type="button"
          onClick={() => setView('entries')}
          className={`krds-btn medium text dict-tab${view === 'entries' ? ' active' : ''}`}
          style={{
            borderRadius: 0,
            color: view === 'entries' ? '#1d4ed8' : 'var(--color-text-muted)',
            fontWeight: view === 'entries' ? 600 : 400,
          }}
        >
          사전 항목
        </button>
        <button
          type="button"
          onClick={() => setView('revisions')}
          className={`krds-btn medium text dict-tab${view === 'revisions' ? ' active' : ''}`}
          style={{
            borderRadius: 0,
            display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
            color: view === 'revisions' ? '#1d4ed8' : 'var(--color-text-muted)',
            fontWeight: view === 'revisions' ? 600 : 400,
          }}
        >
          <History size={13} />
          버전 이력
        </button>
      </div>

      {view === 'entries' && (
      <>
      <div style={{ display: 'flex', gap: 'var(--space-2)', marginBottom: 'var(--space-6)', borderBottom: '1px solid var(--color-border)' }}>
        {TABS.map((t) => {
          const Icon = t.icon
          const isActive = tab === t.type
          return (
            <button
              key={t.type}
              type="button"
              onClick={() => switchTab(t.type)}
              className={`krds-btn medium text dict-tab${isActive ? ' active' : ''}`}
              style={{
                borderRadius: 0,
                display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
                color: isActive ? '#1d4ed8' : 'var(--color-text-muted)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              <Icon size={14} />
              {t.label}
            </button>
          )
        })}
      </div>

      <div className="dict-layout">
        <div className="dict-card" style={{ padding: 'var(--space-4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-3)' }}>
            <h2 style={{ fontSize: 14, fontWeight: 600 }}>{editingId ? `${activeTab.label} 수정` : `${activeTab.label} 추가`}</h2>
            {editingId && (
              <button type="button" onClick={resetForm} className="krds-btn text xsmall">
                취소
              </button>
            )}
          </div>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)' }}>{activeTab.hint}</p>

          <form onSubmit={handleSubmit}>
            <div className="dict-field">
              <label>{tab === 'stopword' ? '단어' : tab === 'synonym' ? '대표 용어' : '표준 용어'}</label>
              <input
                type="text"
                value={form.term}
                onChange={(e) => setForm({ ...form, term: e.target.value })}
                placeholder="예: 검토"
                className="krds-input small"
              />
            </div>

            {tab === 'stopword' && (
              <div className="dict-field">
                <label>일치 방식</label>
                <select
                  value={form.matchType}
                  onChange={(e) => setForm({ ...form, matchType: e.target.value as MatchType })}
                  className="krds-form-select"
                >
                  {Object.entries(MATCH_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              </div>
            )}

            {tab === 'synonym' && (
              <>
                <div className="dict-field">
                  <label>동의어 (Enter로 추가)</label>
                  <ChipInput
                    values={form.variants}
                    onChange={(variants) => setForm({ ...form, variants })}
                    placeholder="예: AI"
                  />
                </div>
                <div className="dict-field">
                  <label>적용 방향</label>
                  <select
                    value={form.direction}
                    onChange={(e) => setForm({ ...form, direction: e.target.value as SynonymDirection })}
                    className="krds-form-select"
                  >
                    {Object.entries(DIRECTION_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="dict-field">
                  <label>처리 방식</label>
                  <select
                    value={form.processingMode}
                    onChange={(e) => setForm({ ...form, processingMode: e.target.value as SynonymProcessingMode })}
                    className="krds-form-select"
                  >
                    {Object.entries(PROCESSING_MODE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
              </>
            )}

            {tab === 'custom_word' && (
              <>
                <div className="dict-field">
                  <label>변형 표현 (오탈자/별칭, Enter로 추가)</label>
                  <ChipInput
                    values={form.variants}
                    onChange={(variants) => setForm({ ...form, variants })}
                    placeholder="예: 랭그래프"
                  />
                </div>
                <div className="dict-field">
                  <label>용어 유형</label>
                  <select
                    value={form.termType}
                    onChange={(e) => setForm({ ...form, termType: e.target.value as UserTermType })}
                    className="krds-form-select"
                  >
                    {Object.entries(TERM_TYPE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="dict-field">
                  <label>처리 규칙</label>
                  <select
                    value={form.processingRule}
                    onChange={(e) => setForm({ ...form, processingRule: e.target.value as UserProcessingRule })}
                    className="krds-form-select"
                  >
                    {Object.entries(PROCESSING_RULE_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                </div>
                <div className="dict-field">
                  <label>발음</label>
                  <input
                    type="text"
                    value={form.pronunciation}
                    onChange={(e) => setForm({ ...form, pronunciation: e.target.value })}
                    placeholder="예: 랭그래프"
                    className="krds-input small"
                  />
                </div>
              </>
            )}

            <div className="dict-field">
              <label>{tab === 'stopword' ? '제외 사유' : tab === 'synonym' ? '설명' : '정의'}</label>
              <input
                type="text"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                placeholder="선택 입력"
                className="krds-input small"
              />
            </div>

            <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
              <div className="dict-field" style={{ flex: 1, minWidth: 0 }}>
                <label>언어</label>
                <input
                  type="text"
                  value={form.language}
                  onChange={(e) => setForm({ ...form, language: e.target.value })}
                  placeholder="예: ko, en, all"
                  className="krds-input small"
                  style={{ width: '100%' }}
                />
              </div>
              <div className="dict-field" style={{ flex: 2, minWidth: 0 }}>
                <label>적용 범위 (쉼표로 구분)</label>
                <input
                  type="text"
                  value={form.scope}
                  onChange={(e) => setForm({ ...form, scope: e.target.value })}
                  placeholder="ALL"
                  className="krds-input small"
                  style={{ width: '100%' }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: 'var(--space-4)', marginBottom: 'var(--space-4)' }}>
              <div className="krds-form-check">
                <input
                  id="dict_case_sensitive_chk"
                  type="checkbox"
                  className="chk"
                  checked={form.caseSensitive}
                  onChange={(e) => setForm({ ...form, caseSensitive: e.target.checked })}
                />
                <label htmlFor="dict_case_sensitive_chk">대소문자 구분</label>
              </div>
              <div className="krds-form-check">
                <input
                  id="dict_enabled_chk"
                  type="checkbox"
                  className="chk"
                  checked={form.enabled}
                  onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                />
                <label htmlFor="dict_enabled_chk">사용여부</label>
              </div>
            </div>

            <button
              type="submit"
              className="krds-btn small primary"
              disabled={isSaving || !form.term.trim() || (tab === 'synonym' && form.variants.length === 0)}
              style={{ width: '100%' }}
            >
              {isSaving ? '저장 중…' : editingId ? '수정 완료' : '추가'}
            </button>
          </form>

          <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 'var(--space-4)', marginTop: 'var(--space-4)' }}>
            <p style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 'var(--space-3)', letterSpacing: 0.2 }}>
              엑셀로 일괄 관리
            </p>
            <div style={{ display: 'flex', gap: 'var(--space-2)' }}>
              <button
                type="button"
                onClick={() => exportEntries.mutate()}
                className="krds-btn small secondary"
                disabled={exportEntries.isPending}
                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-2)' }}
              >
                {exportEntries.isPending ? <Loader2 size={14} style={{ animation: 'dict-spin 1s linear infinite' }} /> : <Download size={14} />}
                다운로드
              </button>
              {exportEntries.isError && (
                <span style={{ fontSize: 11, color: 'var(--color-danger)', alignSelf: 'center' }}>다운로드 실패</span>
              )}
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="krds-btn small secondary"
                disabled={importEntries.isPending}
                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 'var(--space-2)' }}
              >
                {importEntries.isPending ? <Loader2 size={14} style={{ animation: 'dict-spin 1s linear infinite' }} /> : <Upload size={14} />}
                업로드
              </button>
              <input ref={fileInputRef} type="file" accept=".xlsx" onChange={handleImportFile} style={{ display: 'none' }} />
            </div>
            <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 'var(--space-2)' }}>
              {tab === 'stopword' && '단어 | 일치방식 | 대소문자구분(Y/N) | 언어 | 적용범위 | 제외사유 | 사용여부(Y/N)'}
              {tab === 'synonym' && '대표용어 | 동의어(;로 구분) | 적용방향 | 처리방식 | 대소문자구분 | 언어 | 적용범위 | 사용여부'}
              {tab === 'custom_word' && '표준용어 | 변형표현(;로 구분) | 용어유형 | 처리규칙 | 정의 | 대소문자구분 | 언어 | 적용범위 | 사용여부 | 발음'}
              {' '}순서 열을 수정한 뒤 그대로 업로드하면 같은 용어는 갱신, 새 용어는 추가됩니다.
            </p>

            {importFeedback && (
              <div
                style={{
                  marginTop: 'var(--space-3)', padding: 'var(--space-3)', borderRadius: 'var(--radius-md)',
                  fontSize: 12, display: 'flex', gap: 'var(--space-2)', alignItems: 'flex-start',
                  background: importFeedback.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
                  border: `1px solid ${importFeedback.ok ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
                  color: importFeedback.ok ? 'var(--color-success)' : 'var(--color-danger)',
                }}
              >
                {importFeedback.ok ? <CheckCircle2 size={14} style={{ flexShrink: 0, marginTop: 1 }} /> : <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />}
                {importFeedback.ok ? (
                  <span>
                    추가 {importFeedback.result.created}건, 수정 {importFeedback.result.updated}건
                    {importFeedback.result.skipped > 0 && `, 건너뜀 ${importFeedback.result.skipped}건 (행 ${importFeedback.result.skipped_rows.join(', ')})`}
                  </span>
                ) : (
                  <span>{importFeedback.message}</span>
                )}
              </div>
            )}
          </div>
        </div>

        <div className="dict-card" style={{ padding: 'var(--space-4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 'var(--space-4)', gap: 'var(--space-3)', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <h2 style={{ fontSize: 18, fontWeight: 600 }}>저장된 사전 미리보기</h2>
              <span style={{
                fontSize: 11, fontWeight: 600, color: 'var(--color-accent)', background: 'rgba(99,102,241,0.15)',
                borderRadius: 999, padding: '2px 8px',
              }}>
                {data?.items.length ?? 0}건
              </span>
              {(data?.items.length ?? 0) > 0 && (
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                  (사용중 {data?.items.filter((e) => e.enabled).length ?? 0})
                </span>
              )}
            </div>
            <div style={{ position: 'relative', minWidth: 220 }}>
              <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="용어/동의어/설명 검색"
                className="krds-input small"
                style={{ paddingLeft: 30, width: '100%' }}
              />
            </div>
          </div>

          {isLoading && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
              <Loader2 size={24} style={{ animation: 'dict-spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
            </div>
          )}

          {isError && (
            <div style={{
              background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)',
              borderRadius: 'var(--radius-md)', padding: 'var(--space-4)', color: 'var(--color-danger)',
            }}>
              사전 항목을 불러오지 못했습니다.
            </div>
          )}

          {!isLoading && !isError && filtered.length === 0 && (
            <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
              <BookOpen size={40} style={{ margin: '0 auto var(--space-3)', display: 'block', opacity: 0.4 }} />
              <p style={{ fontSize: 13 }}>{filter ? '검색 결과가 없습니다.' : '등록된 항목이 없습니다.'}</p>
            </div>
          )}

          {!isLoading && !isError && filtered.length > 0 && (
            <div className="krds-table-wrap" style={{ overflowX: 'auto' }}>
              <table className="tbl col data">
                <caption className="sr-only">{activeTab.label} 목록</caption>
                <thead>
                  <tr>
                    {columns.map((col) => (
                      <th key={col.header} scope="col" style={col.width ? { width: col.width } : undefined}>
                        {col.header}
                      </th>
                    ))}
                    <th scope="col" style={{ width: '8%' }}>사용여부</th>
                    <th scope="col" style={{ width: '10%' }}>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((entry) => (
                    <tr key={entry.id} className="dict-row">
                      {columns.map((col) => (
                        <td key={col.header}>{col.render(entry)}</td>
                      ))}
                      <td>
                        <button
                          type="button"
                          onClick={() => toggleEnabled(entry)}
                          className="krds-btn text xsmall dict-toggle"
                          style={{
                            color: entry.enabled ? 'var(--color-success)' : 'var(--color-text-muted)',
                            background: entry.enabled ? 'rgba(34,197,94,0.12)' : 'rgba(148,163,184,0.15)',
                          }}
                        >
                          {entry.enabled ? '사용중' : '비활성'}
                        </button>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: 4 }}>
                          <button
                            type="button"
                            onClick={() => startEdit(entry)}
                            aria-label={`${entry.term} 수정`}
                            className="krds-btn text xsmall icon-btn accent"
                          >
                            <Pencil size={12} />
                          </button>
                          <button
                            type="button"
                            onClick={() => deleteEntry.mutate(entry.id)}
                            aria-label={`${entry.term} 삭제`}
                            className="krds-btn text xsmall icon-btn danger"
                          >
                            <Trash2 size={12} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      </>
      )}

      {view === 'revisions' && (
        <div className="dict-card" style={{ padding: 'var(--space-4)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
            <h2 style={{ fontSize: 18, fontWeight: 600 }}>버전 이력</h2>
            <span style={{
              fontSize: 11, fontWeight: 600, color: 'var(--color-accent)', background: 'rgba(99,102,241,0.15)',
              borderRadius: 999, padding: '2px 8px',
            }}>
              최근 {revisionsData?.revisions.length ?? 0}건
            </span>
          </div>
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 'var(--space-4)' }}>
            사전 항목의 추가·수정·삭제·엑셀 가져오기 이력입니다. 변경 전/후 값은 표시하지 않으며, 누가·언제·무엇을 했는지만 보여줍니다.
          </p>

          {revisionsLoading && (
            <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
              <Loader2 size={24} style={{ animation: 'dict-spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
            </div>
          )}

          {!revisionsLoading && (revisionsData?.revisions.length ?? 0) === 0 && (
            <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
              <Clock size={40} style={{ margin: '0 auto var(--space-3)', display: 'block', opacity: 0.4 }} />
              <p style={{ fontSize: 13 }}>변경 이력이 없습니다.</p>
            </div>
          )}

          {!revisionsLoading && (revisionsData?.revisions.length ?? 0) > 0 && (
            <div className="krds-table-wrap" style={{ overflowX: 'auto' }}>
              <table className="tbl col data">
                <caption className="sr-only">사전 버전 이력</caption>
                <thead>
                  <tr>
                    <th scope="col" style={{ width: '8%' }}>버전</th>
                    <th scope="col">용어</th>
                    <th scope="col" style={{ width: '10%' }}>유형</th>
                    <th scope="col" style={{ width: '10%' }}>변경</th>
                    <th scope="col" style={{ width: '14%' }}>작성자</th>
                    <th scope="col" style={{ width: '18%' }}>일시</th>
                  </tr>
                </thead>
                <tbody>
                  {revisionsData?.revisions.map((rev) => (
                    <tr key={rev.version} className="dict-row">
                      <td>{rev.version}</td>
                      <td>{rev.entry_term ?? <span style={{ color: 'var(--color-text-muted)' }}>(삭제된 항목)</span>}</td>
                      <td>{rev.entry_type ? TABS.find((t) => t.type === rev.entry_type)?.label ?? rev.entry_type : '-'}</td>
                      <td>{REVISION_CHANGE_LABELS[rev.change_type] ?? rev.change_type}</td>
                      <td>{rev.created_by_name ?? <span style={{ color: 'var(--color-text-muted)' }}>-</span>}</td>
                      <td>{new Date(rev.created_at).toLocaleString('ko-KR')}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {impact && (
        <div
          style={{
            position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.5)',
            display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
          }}
        >
          <section className="krds-modal fade shown in" role="dialog">
            <div className="modal-dialog modal-sm">
              <div className="modal-content">
                <div className="modal-header">
                  <h2 className="modal-title">영향 문서 {impact.affected_document_count}건</h2>
                </div>
                <div className="modal-conts">
                  <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
                    <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
                      이 사전 항목이 이미 적용된 문서입니다. 변경 사항을 반영하려면 재처리가 필요합니다.
                    </p>
                    <div style={{
                      maxHeight: 180, overflowY: 'auto', border: '1px solid var(--color-border)',
                      borderRadius: 'var(--radius-md)',
                    }}>
                      {impact.documents.map((doc) => (
                        <div key={doc.id} style={{ padding: '6px 10px', fontSize: 12, borderBottom: '1px solid #f1f5f9' }}>
                          {doc.filename}
                        </div>
                      ))}
                    </div>
                    {reprocessDone !== null && (
                      <p style={{ fontSize: 12, color: 'var(--color-success)', margin: 0 }}>
                        {reprocessDone}건 재처리를 시작했습니다.
                      </p>
                    )}
                    <div className="modal-btn btn-wrap">
                      <button
                        type="button"
                        onClick={() => { setImpact(null); setReprocessDone(null) }}
                        className="krds-btn medium secondary"
                      >
                        나중에
                      </button>
                      <button
                        type="button"
                        onClick={handleReprocessAffected}
                        disabled={startPartialReprocess.isPending || reprocessDone !== null}
                        className="krds-btn medium primary"
                      >
                        {startPartialReprocess.isPending ? '재처리 시작 중…' : `${impact.affected_document_count}건 재처리`}
                      </button>
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  className="krds-btn medium icon btn-close close-modal"
                  onClick={() => { setImpact(null); setReprocessDone(null) }}
                >
                  <span className="sr-only">닫기</span>
                  <X size={20} />
                </button>
              </div>
            </div>
            <div className="modal-back"></div>
          </section>
        </div>
      )}
    </div>
  )
}
