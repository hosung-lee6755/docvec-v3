import { useState } from 'react'
import { DEFAULT_SEARCH_SETTINGS, useUpdateCollection, type Collection, type SearchSettings } from '../../hooks/useCollections'
import { Alert, Button, Select } from '../ui'

// v3 마일스톤 6 — 컬렉션 검색 설정. 이 컬렉션의 검색 화면과 채팅이 함께 따른다.
// 컬렉션 수정 창의 <form> 안에 들어가므로 버튼은 모두 type="button"이고, 저장은 따로 한다.

const TOP_K_OPTIONS = [3, 4, 5, 6, 8, 10]

const ROW_STYLE = {
  display: 'grid',
  gridTemplateColumns: 'max-content 1fr',
  gap: 'var(--space-2) var(--space-4)',
  alignItems: 'center',
  fontSize: 'var(--text-sm)',
} as const

const HINT_STYLE = { marginLeft: 'var(--space-2)', color: 'var(--color-text-muted)' } as const

export function SearchSettingsSection({ collection }: { collection: Collection }) {
  const saved = collection.search_settings ?? DEFAULT_SEARCH_SETTINGS
  const [draft, setDraft] = useState<SearchSettings>(saved)
  const update = useUpdateCollection()
  const isDirty = JSON.stringify(draft) !== JSON.stringify(saved)
  const set = <K extends keyof SearchSettings>(key: K, value: SearchSettings[K]) =>
    setDraft((prev) => ({ ...prev, [key]: value }))

  return (
    <fieldset
      style={{
        border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)',
        padding: 'var(--space-4)', margin: 0, minWidth: 0,
        display: 'flex', flexDirection: 'column', gap: 'var(--space-3)',
      }}
    >
      <legend style={{ fontSize: 'var(--text-base)', fontWeight: 600, padding: '0 var(--space-1)' }}>검색 설정</legend>
      <p style={{ fontSize: 'var(--text-sm)', color: 'var(--color-text-muted)', margin: 0 }}>
        이 컬렉션을 검색하거나 이 컬렉션으로 채팅할 때 따르는 방식입니다. 프로젝트 전체를 대상으로 한 채팅은 기본값을 씁니다.
      </p>

      <div style={ROW_STYLE}>
        <label htmlFor="search_mode">검색 방식</label>
        <Select
          id="search_mode"
          controlSize="sm"
          value={draft.mode}
          onChange={(e) => set('mode', e.target.value as SearchSettings['mode'])}
        >
          <option value="hybrid">하이브리드(뜻과 키워드를 함께)</option>
          <option value="vector">의미 검색(뜻만)</option>
        </Select>

        {draft.mode === 'hybrid' && (
          <>
            <label htmlFor="search_weight">의미 비중</label>
            <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
              <input
                id="search_weight"
                type="range"
                min={0.1}
                max={0.9}
                step={0.1}
                value={draft.vector_weight}
                onChange={(e) => set('vector_weight', Number(e.target.value))}
                style={{ flex: 1 }}
              />
              <span style={{ minWidth: 120, color: 'var(--color-text-muted)' }}>
                의미 {Math.round(draft.vector_weight * 100)}% · 키워드 {Math.round((1 - draft.vector_weight) * 100)}%
              </span>
            </span>
          </>
        )}

        <label htmlFor="search_top_k">채팅 근거 수</label>
        <Select
          id="search_top_k"
          controlSize="sm"
          value={draft.top_k}
          onChange={(e) => set('top_k', Number(e.target.value))}
        >
          {TOP_K_OPTIONS.map((n) => <option key={n} value={n}>{n}건</option>)}
        </Select>

        <label htmlFor="search_rerank">재순위</label>
        <span>
          <input id="search_rerank" type="checkbox" checked={draft.rerank} onChange={(e) => set('rerank', e.target.checked)} />
          <span style={HINT_STYLE}>
            채팅에서 질문과 본문을 함께 읽고 근거를 다시 고릅니다. 끄면 빨라지지만 근거가 덜 정확할 수 있습니다.
          </span>
        </span>

        <label htmlFor="search_diversify">다양성</label>
        <span>
          <input id="search_diversify" type="checkbox" checked={draft.diversify} onChange={(e) => set('diversify', e.target.checked)} />
          <span style={HINT_STYLE}>비슷한 발췌문이 겹쳐 나오지 않게 고릅니다.</span>
        </span>
      </div>

      {update.isError && <Alert tone="danger">저장하지 못했습니다. 권한을 확인하세요.</Alert>}
      {update.isSuccess && !isDirty && (
        <span style={{ fontSize: 'var(--text-xs)', color: 'var(--color-text-muted)' }}>저장했습니다.</span>
      )}

      <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end', alignItems: 'center' }}>
        <Button variant="ghost" size="sm" onClick={() => setDraft(DEFAULT_SEARCH_SETTINGS)}>
          기본값으로
        </Button>
        <Button
          variant="primary"
          size="sm"
          disabled={!isDirty || update.isPending}
          onClick={() => update.mutate({ id: collection.id, search_settings: draft })}
        >
          검색 설정 저장
        </Button>
      </div>
    </fieldset>
  )
}
