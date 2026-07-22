import { useMemo, useState } from 'react'
import { X } from 'lucide-react'
import { useCollections, useUpdateCollection } from '../../hooks/useCollections'
import { useWorkflowVersions } from '../../hooks/useWorkflows'

interface SetCollectionDefaultModalProps {
  projectId: string
  workflowId: string
  workflowName: string
  // ANALYSIS는 시스템 기본값 개념이 없다(표준 워크플로우는 PREPROCESS 전용) —
  // isSystemDefault는 kind==='PREPROCESS'일 때만 의미를 가진다.
  kind: 'PREPROCESS' | 'ANALYSIS'
  isSystemDefault?: boolean
  onClose: () => void
}

export default function SetCollectionDefaultModal({
  projectId, workflowId, workflowName, kind, isSystemDefault, onClose,
}: SetCollectionDefaultModalProps) {
  const { data, isLoading } = useCollections(projectId)
  const collections = data?.items ?? []
  const updateCollection = useUpdateCollection()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  // 버전 고정 — CollectionsPage 편집 폼과 동일한 기능(사용자 확인 2026-07-20,
  // "add version-pinning to the row-menu modal so both are equally capable").
  // 시스템 기본 워크플로우는 버전 개념 없이 항상 최신으로 폴백되므로 해당 없음.
  const [versionMode, setVersionMode] = useState<'latest' | 'pinned'>('latest')
  const [versionNumber, setVersionNumber] = useState<number | null>(null)
  const { data: workflowVersions } = useWorkflowVersions(!isSystemDefault ? workflowId : null)
  const publishedVersions = useMemo(
    () => (workflowVersions?.items ?? []).filter((v) => v.published_at).sort((a, b) => b.version_number - a.version_number),
    [workflowVersions],
  )

  const isCurrentDefault = (collection: { default_workflow_id: string | null; default_analysis_workflow_id: string | null }) =>
    kind === 'PREPROCESS'
      ? (isSystemDefault ? !collection.default_workflow_id : collection.default_workflow_id === workflowId)
      : collection.default_analysis_workflow_id === workflowId

  const handleApply = () => {
    if (!selectedId) return
    const collection = collections.find((c) => c.id === selectedId)
    if (!collection) return
    const pinnedVersion = versionMode === 'pinned' ? versionNumber : null
    if (kind === 'ANALYSIS') {
      updateCollection.mutate(
        { id: selectedId, name: collection.name, default_analysis_workflow_id: workflowId, default_analysis_workflow_version: pinnedVersion },
        { onSuccess: onClose },
      )
      return
    }
    // The system default workflow's canonical representation everywhere else
    // is default_workflow_id = null, not its literal id — write it that way
    // so the collection edit dropdown's "표준 전처리 (시스템 기본값)" option matches.
    updateCollection.mutate(
      isSystemDefault
        ? { id: selectedId, name: collection.name, clear_default_workflow: true }
        : { id: selectedId, name: collection.name, default_workflow_id: workflowId, default_workflow_version: pinnedVersion },
      { onSuccess: onClose },
    )
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <div style={{
        background: 'var(--color-surface)', color: 'var(--color-text)', borderRadius: 'var(--radius-md)',
        padding: 'var(--space-5)', width: 400, display: 'flex', flexDirection: 'column', gap: 'var(--space-3)',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0 }}>컬렉션 기본으로 지정</h2>
          <button type="button" onClick={onClose} className="krds-btn text xsmall" style={{ cursor: 'pointer', color: 'var(--color-text)' }}>
            <X size={16} />
          </button>
        </div>
        <p style={{ fontSize: 12.5, color: 'var(--color-text-muted)', margin: 0 }}>
          {kind === 'ANALYSIS'
            ? <>&quot;{workflowName}&quot;을(를) 기본 분석 워크플로우로 지정할 컬렉션을 선택하세요. 지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다.</>
            : <>&quot;{workflowName}&quot;을(를) 기본 전처리 워크플로우로 지정할 컬렉션을 선택하세요. 이후 업로드되는 문서부터 적용됩니다.</>}
        </p>

        {!isSystemDefault && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span style={{ fontSize: 12, fontWeight: 600 }}>적용할 버전</span>
            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="radio"
                id="set_default_version_latest"
                name="set_default_version_mode"
                checked={versionMode === 'latest'}
                onChange={() => { setVersionMode('latest'); setVersionNumber(null) }}
              />
              <label htmlFor="set_default_version_latest" style={{ fontSize: 13, fontWeight: 400 }}>
                항상 최신 발행 버전
              </label>
            </div>
            <div className="krds-form-check" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <input
                type="radio"
                id="set_default_version_pinned"
                name="set_default_version_mode"
                checked={versionMode === 'pinned'}
                onChange={() => setVersionMode('pinned')}
              />
              <label htmlFor="set_default_version_pinned" style={{ fontSize: 13, fontWeight: 400 }}>
                버전 고정
              </label>
              {versionMode === 'pinned' && (
                <select
                  className="krds-form-select"
                  style={{ marginLeft: 6, width: 'auto' }}
                  value={versionNumber ?? ''}
                  onChange={(e) => setVersionNumber(e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">선택</option>
                  {publishedVersions.map((v) => (
                    <option key={v.id} value={v.version_number}>v{v.version_number}</option>
                  ))}
                </select>
              )}
            </div>
          </div>
        )}

        {isLoading && <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>불러오는 중...</p>}
        {!isLoading && !collections.length && (
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>이 프로젝트에 컬렉션이 없습니다.</p>
        )}
        {!!collections.length && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflowY: 'auto' }}>
            {collections.map((collection) => (
              <div
                key={collection.id}
                className="krds-form-check"
                style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 4 }}
              >
                <input
                  type="radio"
                  id={`target_collection_${collection.id}`}
                  name="target_collection"
                  checked={selectedId === collection.id}
                  onChange={() => setSelectedId(collection.id)}
                />
                <label htmlFor={`target_collection_${collection.id}`} style={{ fontSize: 13 }}>
                  {collection.name}
                  {isCurrentDefault(collection) && (
                    <span style={{ color: 'var(--color-text-muted)' }}> (현재 기본)</span>
                  )}
                </label>
              </div>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 'var(--space-2)' }}>
          <button type="button" onClick={onClose} className="krds-btn secondary small" style={{ cursor: 'pointer' }}>취소</button>
          <button
            type="button"
            onClick={handleApply}
            disabled={!selectedId || updateCollection.isPending}
            className="krds-btn primary small"
            style={{ cursor: 'pointer' }}
          >
            지정
          </button>
        </div>
      </div>
    </div>
  )
}
