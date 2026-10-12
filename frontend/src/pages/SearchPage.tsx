import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Search, History, FileText } from 'lucide-react'
import { apiClient } from '../lib/apiClient'
import { useCollections } from '../hooks/useCollections'
import { useAllTags } from '../hooks/useDocuments'
import { useSearchHistory } from '../hooks/useSearchHistory'

interface SearchResult {
  chunk_id: string
  score: number
  document_id: string
  content: string
  metadata: Record<string, unknown>
  bm25_score: number | null
  final_score: number | null
}

interface SearchResponse {
  items: SearchResult[]
  expanded_query: string
  added_terms: string[]
}

type SearchMode = 'vector' | 'hybrid'

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
        limit: 10,
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
    <div>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-6)' }}>의미 검색</h1>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)', marginBottom: 'var(--space-6)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 'var(--space-2)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
            <select
              value={collectionId}
              onChange={(e) => setCollectionId(e.target.value)}
              disabled={collectionsLoading}
              className="krds-form-select small"
              style={{ flex: '0 0 180px', width: 180 }}
            >
              <option value="">전체 문서 검색</option>
              {collectionsData?.items.map((col) => (
                <option key={col.id} value={col.id}>{col.name}</option>
              ))}
            </select>

            <div style={{ display: 'flex', gap: 'var(--space-1)' }}>
              {(['vector', 'hybrid'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setMode(m)}
                  className={`krds-btn small ${mode === m ? 'primary' : 'tertiary'}`}
                >
                  {m === 'vector' ? '의미 검색' : '하이브리드(BM25)'}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={() => setDiversify((v) => !v)}
              title="비슷한 청크가 중복 노출되지 않도록 결과를 다양화합니다"
              className={`krds-btn small ${diversify ? 'primary' : 'tertiary'}`}
            >
              다양성 검색
            </button>

            <input
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder="태그 필터"
              className="krds-input small"
              style={{ width: 140 }}
              list="tag-suggestions"
            />
            <datalist id="tag-suggestions">
              {(allTagsData?.tags ?? []).map((t) => (
                <option key={t} value={t} />
              ))}
            </datalist>

            <button
              type="button"
              onClick={() => setShowScores((v) => !v)}
              className={`krds-btn small ${showScores ? 'primary' : 'tertiary'}`}
            >
              상세 점수
            </button>
          </div>

          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="krds-btn text small"
          >
            <History size={14} /> 최근 검색
          </button>
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="문서 내용 검색..."
            className="krds-input small"
            style={{ flex: '1 1 auto', width: '100%' }}
          />

          <button
            type="submit"
            disabled={search.isPending || !canSearch}
            className="krds-btn small primary"
          >
            {search.isPending
              ? <div className="krds-spinner" role="status" style={{ width: 16, height: 16 }}><span className="sr-only">로딩 중</span></div>
              : <Search size={16} />}
            검색
          </button>
        </div>

        {showHistory && (
          <div style={{
            border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)',
            background: '#fff', padding: 'var(--space-2)',
          }}>
            {!historyData?.items.length && (
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 'var(--space-2)' }}>
                최근 검색 기록이 없습니다.
              </p>
            )}
            {historyData?.items.map((h) => (
              <button
                key={h.id}
                type="button"
                onClick={() => runSearch(h.query, h.search_mode === 'hybrid' ? 'hybrid' : 'vector')}
                className="krds-btn text"
                style={{ display: 'flex', justifyContent: 'space-between', width: '100%', textAlign: 'left' }}
              >
                <span>{h.query}</span>
                <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                  {h.result_count}건 · {h.search_mode}
                </span>
              </button>
            ))}
          </div>
        )}

        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
          {collectionId
            ? '선택한 컬렉션 내에서 검색합니다.'
            : '컬렉션을 선택하면 해당 컬렉션 내에서만 검색합니다.'}
        </p>
      </form>

      {search.isPending && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <div className="krds-spinner" role="status"><span className="sr-only">로딩 중</span></div>
        </div>
      )}

      {search.isError && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          color: '#dc2626', marginBottom: 'var(--space-4)',
        }}>
          검색 중 오류가 발생했습니다.
        </div>
      )}

      {!search.isPending && search.isSuccess && search.data.items.length === 0 && (
        <div style={{ textAlign: 'center', padding: 'var(--space-8)', color: 'var(--color-text-muted)' }}>
          <p>검색 결과가 없습니다.</p>
        </div>
      )}

      {!search.isPending && search.data && (search.data.items.length ?? 0) > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
            {search.data.items.length}개 결과
            {!!search.data.added_terms.length && (
              <span style={{ marginLeft: 'var(--space-2)', color: 'var(--color-text-muted)' }}>
                · 사전에 등록된 동의어로 확장됨: {search.data.added_terms.join(', ')}
              </span>
            )}
          </p>
          {search.data.items.map((result) => (
            <div key={result.chunk_id} style={{
              background: '#fff', border: '1px solid #e2e8f0',
              borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-2)' }}>
                <button
                  type="button"
                  onClick={() => navigate(projectId ? `/projects/${projectId}/documents/${result.document_id}` : `/documents/${result.document_id}`)}
                  title="문서 상세보기"
                  className="krds-btn text small"
                >
                  <FileText size={12} />
                  {typeof result.metadata.filename === 'string' ? result.metadata.filename : `문서 ${result.document_id.slice(0, 8)}...`}
                </button>
                <span className="krds-badge small bg-secondary" style={{ flexShrink: 0 }}>
                  {((result.final_score ?? result.score) * 100).toFixed(1)}%
                  {result.bm25_score != null && ' (하이브리드)'}
                </span>
              </div>
              {showScores && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 'var(--space-2)' }}>
                  <span className="krds-badge small bg-gray">벡터 {(result.score * 100).toFixed(1)}</span>
                  {result.bm25_score != null && (
                    <span className="krds-badge small bg-gray">BM25 {(result.bm25_score * 100).toFixed(1)}</span>
                  )}
                  {result.final_score != null && (
                    <span className="krds-badge small bg-information">최종 {(result.final_score * 100).toFixed(1)}</span>
                  )}
                  {typeof result.metadata.chunk_index === 'number' && (
                    <span className="krds-badge small bg-gray">청크 #{(result.metadata.chunk_index as number) + 1}</span>
                  )}
                  {typeof result.metadata.page_number === 'number' && (
                    <span className="krds-badge small bg-gray">{result.metadata.page_number as number}쪽</span>
                  )}
                  {Array.isArray(result.metadata.tags) && (result.metadata.tags as string[]).map((t) => (
                    <span key={t} className="krds-badge small bg-secondary">#{t}</span>
                  ))}
                </div>
              )}
              <p style={{ fontSize: 14, lineHeight: 1.6, margin: 0 }}>{result.content}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
