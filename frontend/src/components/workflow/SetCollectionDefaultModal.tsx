import { useMemo, useState } from 'react'
import { useCollections, useUpdateCollection } from '../../hooks/useCollections'
import { useWorkflowVersions } from '../../hooks/useWorkflows'
import { Button, ErrorAlert, Modal, Select } from '../ui'
import '../../styles/screens/pipeline.css'

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
  // 버전 고정 — CollectionsPage 편집 폼과 동일한 기능.
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
    <Modal
      isOpen
      title="컬렉션 기본으로 지정"
      onClose={onClose}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button variant="primary" onClick={handleApply} disabled={!selectedId || updateCollection.isPending}>
            지정
          </Button>
        </>
      )}
    >
      <div className="pipeline-modal-stack">
        {updateCollection.isError && <ErrorAlert error={updateCollection.error} message="컬렉션 기본 워크플로우로 지정하지 못했습니다." />}
        <p className="wf-muted" style={{ fontSize: 'var(--text-sm)' }}>
          {kind === 'ANALYSIS'
            ? <>&quot;{workflowName}&quot;을(를) 기본 분석 워크플로우로 지정할 컬렉션을 선택하세요. 지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다.</>
            : <>&quot;{workflowName}&quot;을(를) 기본 전처리 워크플로우로 지정할 컬렉션을 선택하세요. 이후 업로드되는 문서부터 적용됩니다.</>}
        </p>

        {!isSystemDefault && (
          <fieldset style={{ border: 0, margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
            <legend className="block-panel__label" style={{ marginBottom: 4 }}>적용할 버전</legend>
            <div className="pipeline-radios">
              <label>
                <input
                  type="radio"
                  id="set_default_version_latest"
                  name="set_default_version_mode"
                  checked={versionMode === 'latest'}
                  onChange={() => { setVersionMode('latest'); setVersionNumber(null) }}
                />
                항상 최신 발행 버전
              </label>
              <label>
                <input
                  type="radio"
                  id="set_default_version_pinned"
                  name="set_default_version_mode"
                  checked={versionMode === 'pinned'}
                  onChange={() => setVersionMode('pinned')}
                />
                버전 고정
              </label>
            </div>
            {versionMode === 'pinned' && (
              <Select
                aria-label="고정할 버전"
                controlSize="sm"
                style={{ width: 'auto' }}
                value={versionNumber ?? ''}
                onChange={(e) => setVersionNumber(e.target.value ? Number(e.target.value) : null)}
              >
                <option value="">선택</option>
                {publishedVersions.map((v) => (
                  <option key={v.id} value={v.version_number}>v{v.version_number}</option>
                ))}
              </Select>
            )}
          </fieldset>
        )}

        {isLoading && <p className="wf-muted">불러오는 중...</p>}
        {!isLoading && !collections.length && (
          <p className="wf-muted">이 프로젝트에 컬렉션이 없습니다.</p>
        )}
        {!!collections.length && (
          <div className="pipeline-modal-list" style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 240, overflowY: 'auto' }}>
            {collections.map((collection) => (
              <div key={collection.id} className="pipeline-radios" style={{ padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}>
                <label>
                  <input
                    type="radio"
                    id={`target_collection_${collection.id}`}
                    name="target_collection"
                    checked={selectedId === collection.id}
                    onChange={() => setSelectedId(collection.id)}
                  />
                  {collection.name}
                  {isCurrentDefault(collection) && (
                    <span className="wf-muted"> (현재 기본)</span>
                  )}
                </label>
              </div>
            ))}
          </div>
        )}
      </div>
    </Modal>
  )
}
