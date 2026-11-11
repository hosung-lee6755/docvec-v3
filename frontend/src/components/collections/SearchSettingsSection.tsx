import { useState } from 'react'
import { DEFAULT_SEARCH_SETTINGS, useUpdateCollection, type Collection, type SearchSettings } from '../../hooks/useCollections'

// v3 마일스톤 6 — 컬렉션 검색 설정. 이 컬렉션의 검색 화면과 채팅이 함께 따른다.
// 컬렉션 수정 창의 <form> 안에 들어가므로 버튼은 모두 type="button"이고, 저장은 따로 한다.

const TOP_K_OPTIONS = [3, 4, 5, 6, 8, 10]

export function SearchSettingsSection({ collection }: { collection: Collection }) {
  const saved = collection.search_settings ?? DEFAULT_SEARCH_SETTINGS
  const [draft, setDraft] = useState<SearchSettings>(saved)
  const update = useUpdateCollection()
  const isDirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const set = <K extends keyof SearchSettings>(key: K, value: SearchSettings[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  return (
    <fieldset style={{ border: '1px solid #e2e8f0', borderRadius: 'var(--radius-md)', padding: 'var(--space-3)', marginBottom: 'var(--space-3)' }}>
      <legend style={{ fontSize: 14, fontWeight: 600, padding: '0 4px' }}>검색 설정</legend>
      <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 var(--space-3)' }}>
        이 컬렉션을 검색하거나 이 컬렉션으로 채팅할 때 따르는 방식입니다. 프로젝트 전체를 대상으로 한 채팅은 기본값을 씁니다.
      </p>

      <div style={{ display: 'grid', gridTemplateColumns: 'max-content 1fr', gap: 'var(--space-2) var(--space-3)', alignItems: 'center', fontSize: 13 }}>
        <label htmlFor="search_mode">검색 방식</label>
        <select id="search_mode" className="krds-form-select small" value={draft.mode}
          onChange={(e) => set('mode', e.target.value as SearchSettings['mode'])}>
          <option value="hybrid">하이브리드(뜻과 키워드를 함께)</option>
          <option value="vector">의미 검색(뜻만)</option>
        </select>

        {draft.mode === 'hybrid' && (
          <>
            <label htmlFor="search_weight">의미 비중</label>
            <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <input id="search_weight" type="range" min={0.1} max={0.9} step={0.1} value={draft.vector_weight}
                onChange={(e) => set('vector_weight', Number(e.target.value))} style={{ flex: 1 }} />
              <span style={{ minWidth: 120 }}>
                의미 {Math.round(draft.vector_weight * 100)}% · 키워드 {Math.round((1 - draft.vector_weight) * 100)}%
              </span>
            </span>
          </>
        )}

        <label htmlFor="search_top_k">채팅 근거 수</label>
        <select id="search_top_k" className="krds-form-select small" value={draft.top_k}
          onChange={(e) => set('top_k', Number(e.target.value))}>
          {TOP_K_OPTIONS.map((n) => <option key={n} value={n}>{n}건</option>)}
        </select>

        <label htmlFor="search_rerank">재순위</label>
        <span>
          <input id="search_rerank" type="checkbox" checked={draft.rerank} onChange={(e) => set('rerank', e.target.checked)} />
          <span style={{ marginLeft: 6, color: 'var(--color-text-muted)' }}>
            채팅에서 질문과 본문을 함께 읽고 근거를 다시 고릅니다. 끄면 빨라지지만 근거가 덜 정확할 수 있습니다.
          </span>
        </span>

        <label htmlFor="search_diversify">다양성</label>
        <span>
          <input id="search_diversify" type="checkbox" checked={draft.diversify} onChange={(e) => set('diversify', e.target.checked)} />
          <span style={{ marginLeft: 6, color: 'var(--color-text-muted)' }}>비슷한 발췌문이 겹쳐 나오지 않게 고릅니다.</span>
        </span>
      </div>

      <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', alignItems: 'center', marginTop: 'var(--space-3)' }}>
        {update.isError && <span role="alert" style={{ fontSize: 12, color: '#dc2626' }}>저장하지 못했습니다. 권한을 확인하세요.</span>}
        {update.isSuccess && !isDirty && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>저장했습니다.</span>}
        <button type="button" className="krds-btn xsmall tertiary" onClick={() => setDraft(DEFAULT_SEARCH_SETTINGS)}>
          기본값으로
        </button>
        <button type="button" className="krds-btn xsmall primary" disabled={!isDirty || update.isPending}
          onClick={() => update.mutate({ id: collection.id, search_settings: draft })}>
          검색 설정 저장
        </button>
      </div>
    </fieldset>
  )
}
