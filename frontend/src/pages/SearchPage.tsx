import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, History, FileText } from 'lucide-react'
import { apiClient } from '../lib/apiClient'
import { useCollections } from '../hooks/useCollections'
import { useAllTags } from '../hooks/useDocuments'
import { useSearchHistory } from '../hooks/useSearchHistory'
import { CitationEvidence, LowOcrBadge, type RetrievalEvidence } from '../components/chat/CitationEvidence'
import { Badge, Button, EmptyState, ErrorAlert, FilterChip, Input, Page, PageBody, PageHeader, SearchInput, Segmented, Select, Toolbar } from '../components/ui'
import '../styles/screens/user.css'

interface SearchResult {
  chunk_id: string
  score: number
  document_id: string
  content: string
  metadata: Record<string, unknown>
  bm25_score: number | null
  final_score: number | null
  // v3 마일스톤 6: 질문과 겹친 낱말, 그 쪽의 OCR 신뢰도
  evidence?: RetrievalEvidence | null
}

interface AppliedSearchSettings {
  mode: SearchMode
  diversify: boolean
  vector_weight: number
  rerank_in_chat: boolean
  from_collection: boolean
}

interface SearchResponse {
  items: SearchResult[]
  expanded_query: string
  added_terms: string[]
  applied?: AppliedSearchSettings | null
}

type SearchMode = 'vector' | 'hybrid'

const RESULT_LIMITS = [5, 10, 20, 30]

const MODE_OPTIONS: ReadonlyArray<{ value: SearchMode; label: string }> = [
  { value: 'vector', label: '의미 검색' },
  { value: 'hybrid', label: '하이브리드(BM25)' },
]

function appliedSummary(applied: AppliedSearchSettings): string {
  const how = applied.mode === 'hybrid'
    ? `하이브리드(의미 ${Math.round(applied.vector_weight * 100)}%, 키워드 ${Math.round((1 - applied.vector_weight) * 100)}%)`
    : '의미 검색'
  const origin = applied.from_collection ? '컬렉션 설정 기준' : '이 화면에서 고른 설정'
  return `${how}${applied.diversify ? ', 다양성 검색' : ''} · ${origin} · 재순위는 채팅에서만 합니다(이 설정: ${applied.rerank_in_chat ? '켬' : '끔'})`
}

export default function SearchPage() {
  const navigate = useNavigate()
  const { projectId } = useParams<{ projectId?: string }>()
  const [query, setQuery] = useState('')
  const [collectionId, setCollectionId] = useState('')
  const [mode, setMode] = useState<SearchMode>('vector')
  const [diversify, setDiversify] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const [tagFilter, setTagFilter] = useState('')
  const [showScores, setShowScores] = useState(false)
  const [limit, setLimit] = useState(10)
  const { data: collectionsData, isLoading: collectionsLoading } = useCollections(projectId)
  const { data: historyData } = useSearchHistory()
  const { data: allTagsData } = useAllTags()
  const queryClient = useQueryClient()

  const search = useMutation({
    mutationFn: async ({ q, cid, m }: { q: string; cid: string; m: SearchMode }) => {
      const { data } = await apiClient.post('/search', {
        query: q,
        collection_id: cid || null,
        project_id: projectId || null,
        limit,
        mode: m,
        diversify,
        filters: tagFilter.trim() ? { tags: tagFilter.trim() } : null,
      })
      return data as SearchResponse
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['search-history'] })
    },
  })

  const runSearch = (q: string, m: SearchMode = mode) => {
    setQuery(q)
    setShowHistory(false)
    search.mutate({ q, cid: collectionId, m })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (query.trim()) {
      runSearch(query.trim())
    }
  }

  const canSearch = query.trim().length > 0

  return (
    <Page>
      <PageHeader title="의미 검색" />
      <PageBody>
        <form onSubmit={handleSubmit} className="user-search__form">
          <Toolbar label="검색 설정">
            <Select
              controlSize="sm"
              value={collectionId}
              onChange={(e) => {
                // 컬렉션을 고르면 그 컬렉션의 검색 설정(v3 마일스톤 6)을 기본값으로 가져온다
                setCollectionId(e.target.value)
                const picked = collectionsData?.items.find((col) => col.id === e.target.value)
                if (picked?.search_settings) {
                  setMode(picked.search_settings.mode)
                  setDiversify(picked.search_settings.diversify)
                }
              }}
              disabled={collectionsLoading}
              className="user-search__collection"
              aria-label="검색할 컬렉션"
            >
              <option value="">전체 문서 검색</option>
              {collectionsData?.items.map((col) => (
                <option key={col.id} value={col.id}>{col.name}</option>
              ))}
            </Select>

            <Segmented options={MODE_OPTIONS} value={mode} onChange={setMode} label="검색 방식" />

            <FilterChip
              isActive={diversify}
              onClick={() => setDiversify((v) => !v)}
              title="비슷한 청크가 중복 노출되지 않도록 결과를 다양화합니다"
            >
              다양성 검색
            </FilterChip>

            <Select
              controlSize="sm"
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              aria-label="결과 수"
              className="user-search__limit"
            >
              {RESULT_LIMITS.map((n) => <option key={n} value={n}>{n}건</option>)}
            </Select>

            <SearchInput
              label="태그 필터"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              width={160}
              list="tag-suggestions"
            />
            <datalist id="tag-suggestions">
              {(allTagsData?.tags ?? []).map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>

            <FilterChip isActive={showScores} onClick={() => setShowScores((v) => !v)}>
              상세 점수
            </FilterChip>

            <span className="user-search__spacer" />
            <Button variant="ghost" size="sm" onClick={() => setShowHistory((v) => !v)} icon={<History size={14} />}>
              최근 검색
            </Button>
          </Toolbar>

          <div className="user-search__query-row">
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="문서 내용 검색..."
              className="user-search__grow"
            />
            <Button type="submit" variant="primary" disabled={search.isPending || !canSearch} icon={search.isPending
              ? <span className="user-spinner" role="status"><span className="sr-only">로딩 중</span></span>
              : <Search size={16} />}>
              검색
            </Button>
          </div>

          {showHistory && (
            <div className="user-search__history">
              {!historyData?.items.length && (
                <p className="user-search__muted user-search__history-empty">
                  최근 검색 기록이 없습니다.
                </p>
              )}
              {historyData?.items.map((h) => (
                <button
                  key={h.id}
                  type="button"
                  onClick={() => runSearch(h.query, h.search_mode === 'hybrid' ? 'hybrid' : 'vector')}
                  className="user-search__history-item"
                >
                  <span>{h.query}</span>
                  <span className="user-search__history-meta">
                    {h.result_count}건 · {h.search_mode}
                  </span>
                </button>
              ))}
            </div>
          )}

          <p className="user-search__muted">
            {collectionId
              ? '선택한 컬렉션 내에서 검색합니다.'
              : '컬렉션을 선택하면 해당 컬렉션 내에서만 검색합니다.'}
          </p>
        </form>

        {search.isPending && (
          <div className="user-search__loading">
            <div className="user-spinner" role="status"><span className="sr-only">로딩 중</span></div>
          </div>
        )}

        {search.isError && (
          <ErrorAlert error={search.error} message="검색하지 못했습니다." />
        )}

        {!search.isPending && search.isSuccess && search.data.items.length === 0 && (
          <EmptyState title="검색 결과가 없습니다." />
        )}

        {!search.isPending && search.data && (search.data.items.length ?? 0) > 0 && (
          <div className="user-search__results">
            <p className="user-search__muted">
              {search.data.items.length}개 결과
              {!!search.data.added_terms.length && (
                <span className="user-search__added">
                  · 사전에 등록된 동의어로 확장됨: {search.data.added_terms.join(', ')}
                </span>
              )}
            </p>
            {search.data.applied && (
              <p className="user-search__muted">
                검색 방식: {appliedSummary(search.data.applied)}
              </p>
            )}
            {search.data.items.map((result) => (
              <div key={result.chunk_id} className="user-search__result">
                <div className="user-search__result-head">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => navigate(projectId ? `/projects/${projectId}/documents/${result.document_id}` : `/documents/${result.document_id}`)}
                    title="문서 상세보기"
                    icon={<FileText size={12} />}
                  >
                    {typeof result.metadata.filename === 'string' ? result.metadata.filename : `문서 ${result.document_id.slice(0, 8)}...`}
                  </Button>
                  <span className="user-search__result-badges">
                    <LowOcrBadge evidence={result.evidence} />
                    <Badge tone="neutral">
                      {((result.final_score ?? result.score) * 100).toFixed(1)}%
                      {result.bm25_score != null && ' (하이브리드)'}
                    </Badge>
                  </span>
                </div>
                {showScores && (
                  <div className="user-search__chips">
                    <Badge tone="neutral">벡터 {(result.score * 100).toFixed(1)}</Badge>
                    {result.bm25_score != null && (
                      <Badge tone="neutral">BM25 {(result.bm25_score * 100).toFixed(1)}</Badge>
                    )}
                    {result.final_score != null && (
                      <Badge tone="info">최종 {(result.final_score * 100).toFixed(1)}</Badge>
                    )}
                    {typeof result.metadata.chunk_index === 'number' && (
                      <Badge tone="neutral">청크 #{(result.metadata.chunk_index as number) + 1}</Badge>
                    )}
                    {typeof result.metadata.page_number === 'number' && (
                      <Badge tone="neutral">{result.metadata.page_number as number}쪽</Badge>
                    )}
                    {Array.isArray(result.metadata.tags) && (result.metadata.tags as string[]).map((t) => (
                      <Badge key={t} tone="neutral">#{t}</Badge>
                    ))}
                  </div>
                )}
                <p className="user-search__content">{result.content}</p>
                <CitationEvidence evidence={{
                  ...result.evidence,
                  scores: {
                    vector: result.score,
                    ...(result.bm25_score != null ? { bm25: result.bm25_score } : {}),
                    ...(result.final_score != null ? { fused: result.final_score } : {}),
                  },
                }} />
              </div>
            ))}
          </div>
        )}
      </PageBody>
    </Page>
  )
}
