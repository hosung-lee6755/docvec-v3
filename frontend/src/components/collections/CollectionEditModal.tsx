import { useMemo, useState } from 'react'
import { Loader2 } from 'lucide-react'
import {
  useReprocessCollection,
  useUpdateCollection,
  type Collection,
} from '../../hooks/useCollections'
import { useWorkflowGraph, useWorkflowVersions, useWorkflows, type WorkflowGraph } from '../../hooks/useWorkflows'
import { getBlockMeta } from '../../lib/workflowBlocks'
import { apiClient } from '../../lib/apiClient'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../../hooks/useAccess'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'
import { Alert, Button, Field, Input, Modal, Select, Textarea } from '../ui'
import { SearchSettingsSection } from './SearchSettingsSection'
import type { ProjectOption } from './CollectionCreateModal'

// 그래프의 블록 체인을 진입 블록에서부터 첫 번째 나가는 에지를 따라가며 한 줄로
// 요약 — "문서 처리" 섹션이 보여줄 미리보기용 단순화(분기가 있는 그래프는 첫 갈래만 보여준다).
function buildBlockChainPreview(graph: WorkflowGraph): string {
  const hasIncoming = new Set(graph.edges.map((e) => e.to_block_id))
  const outgoing = new Map(graph.edges.map((e) => [e.from_block_id, e.to_block_id]))
  const entry = graph.blocks.find((b) => !hasIncoming.has(b.id))
  if (!entry) return graph.blocks.map((b) => getBlockMeta(b.block_type).label).join(' → ')

  const chain: string[] = []
  let current: typeof entry | undefined = entry
  const visited = new Set<string>()
  while (current && !visited.has(current.id)) {
    chain.push(getBlockMeta(current.block_type).label)
    visited.add(current.id)
    const nextId = outgoing.get(current.id)
    current = nextId ? graph.blocks.find((b) => b.id === nextId) : undefined
  }
  return chain.join(' → ')
}

type VersionMode = 'latest' | 'pinned'
interface VersionOption {
  id: string
  version_number: number
}

interface VersionPickerProps {
  idPrefix: string
  mode: VersionMode
  onModeChange: (mode: VersionMode) => void
  versionNumber: number | null
  onVersionChange: (versionNumber: number | null) => void
  versions: VersionOption[]
}

/** 워크플로우 버전 고정 선택. 항상 최신 발행 버전을 쓰거나 특정 버전에 고정한다. */
function VersionPicker({ idPrefix, mode, onModeChange, versionNumber, onVersionChange, versions }: VersionPickerProps) {
  return (
    <div role="radiogroup" aria-label="버전" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)', fontSize: 'var(--text-sm)' }}>
      <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
        <input
          type="radio"
          id={`${idPrefix}_version_mode_latest`}
          name={`${idPrefix}_version_mode`}
          checked={mode === 'latest'}
          onChange={() => { onModeChange('latest'); onVersionChange(null) }}
        />
        항상 최신 발행 버전
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
          <input
            type="radio"
            id={`${idPrefix}_version_mode_pinned`}
            name={`${idPrefix}_version_mode`}
            checked={mode === 'pinned'}
            onChange={() => onModeChange('pinned')}
          />
          버전 고정
        </label>
        {mode === 'pinned' && (
          <Select
            aria-label="고정할 버전"
            controlSize="sm"
            style={{ width: 'auto' }}
            value={versionNumber ?? ''}
            onChange={(e) => onVersionChange(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">선택</option>
            {versions.map((v) => (
              <option key={v.id} value={v.version_number}>v{v.version_number}</option>
            ))}
          </Select>
        )}
      </div>
    </div>
  )
}

const FORM_ID = 'collection-edit-form'

interface CollectionEditModalProps {
  collection: Collection
  projects: ProjectOption[]
  routeProjectId: string | undefined
  onClose: () => void
}

/** 컬렉션 수정 창. 열릴 때마다 현재 컬렉션 값으로 새로 마운트된다. */
export function CollectionEditModal({ collection, projects, routeProjectId, onClose }: CollectionEditModalProps) {
  const updateCollection = useUpdateCollection()
  const reprocessCollection = useReprocessCollection()
  const [reprocessResult, setReprocessResult] = useState<string | null>(null)
  const [reprocessConfirming, setReprocessConfirming] = useState(false)
  const [isExporting, setIsExporting] = useState(false)

  const [name, setName] = useState(collection.name)
  const [description, setDescription] = useState(collection.description ?? '')
  const [securityLevel, setSecurityLevel] = useState<'' | SecurityLevel>(collection.default_security_level ?? '')
  const [projectId, setProjectId] = useState(collection.project_id ?? '')
  const [isNameMissing, setIsNameMissing] = useState(false)
  const [workflowId, setWorkflowId] = useState(collection.default_workflow_id ?? '')
  const [versionMode, setVersionMode] = useState<VersionMode>(collection.default_workflow_version != null ? 'pinned' : 'latest')
  const [versionNumber, setVersionNumber] = useState<number | null>(collection.default_workflow_version)
  // '' = 자동 분석 없음 — default_analysis_workflow_id가 null일 때의 의미.
  const [analysisWorkflowId, setAnalysisWorkflowId] = useState(collection.default_analysis_workflow_id ?? '')
  const [analysisVersionMode, setAnalysisVersionMode] = useState<VersionMode>(
    collection.default_analysis_workflow_version != null ? 'pinned' : 'latest',
  )
  const [analysisVersionNumber, setAnalysisVersionNumber] = useState<number | null>(collection.default_analysis_workflow_version)

  // 시스템 표준 워크플로우는 project_id가 없어 GET /workflows?project_id=에 절대 나오지 않는다 —
  // 개인(프로젝트 없는) 컬렉션은 "표준 전처리(시스템 기본값)" 옵션 하나만 고를 수 있다.
  const { data: projectPreprocessWorkflows } = useWorkflows(collection.project_id ?? null, 'PREPROCESS')
  const { data: projectAnalysisWorkflows } = useWorkflows(collection.project_id ?? null, 'ANALYSIS')
  const { data: editWorkflowVersions } = useWorkflowVersions(workflowId || null)
  const publishedVersions = useMemo(
    () => (editWorkflowVersions?.items ?? []).filter((v) => v.published_at).sort((a, b) => b.version_number - a.version_number),
    [editWorkflowVersions],
  )
  const previewVersionId = useMemo(() => {
    if (versionMode === 'pinned' && versionNumber != null) {
      return publishedVersions.find((v) => v.version_number === versionNumber)?.id ?? null
    }
    return publishedVersions[0]?.id ?? null
  }, [versionMode, versionNumber, publishedVersions])
  const { data: previewGraph } = useWorkflowGraph(workflowId || null, previewVersionId)
  const { data: analysisWorkflowVersions } = useWorkflowVersions(analysisWorkflowId || null)
  const analysisPublishedVersions = useMemo(
    () => (analysisWorkflowVersions?.items ?? []).filter((v) => v.published_at).sort((a, b) => b.version_number - a.version_number),
    [analysisWorkflowVersions],
  )

  const handleEdit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setIsNameMissing(true)
      return
    }
    setIsNameMissing(false)
    try {
      await updateCollection.mutateAsync({
        id: collection.id,
        name: name.trim(),
        description: description.trim() || undefined,
        project_id: projectId || undefined,
        default_security_level: securityLevel || null,
        ...(workflowId
          ? { default_workflow_id: workflowId, default_workflow_version: versionMode === 'pinned' ? versionNumber : null }
          : { clear_default_workflow: true }),
        ...(analysisWorkflowId
          ? {
            default_analysis_workflow_id: analysisWorkflowId,
            default_analysis_workflow_version: analysisVersionMode === 'pinned' ? analysisVersionNumber : null,
          }
          : { clear_default_analysis_workflow: true }),
      })
      onClose()
    } catch {
      // 창은 열어 둔다. 오류는 updateCollection.isError로 보여 준다.
    }
  }

  const handleReprocess = async () => {
    setReprocessConfirming(false)
    setReprocessResult(null)
    const result = await reprocessCollection.mutateAsync(collection.id)
    setReprocessResult(`${result.queued}건 재처리 시작됨${result.skipped ? ` (${result.skipped}건 건너뜀)` : ''}`)
  }

  const handleExport = async () => {
    setIsExporting(true)
    try {
      const { data } = await apiClient.get(`/collections/${collection.id}/export`, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url
      a.download = `collection-${collection.id}-export.json`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setIsExporting(false)
    }
  }

  const docCount = collection.document_count

  return (
    <Modal
      isOpen
      size="lg"
      isDismissible={false}
      title="컬렉션 수정"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button
            type="submit"
            form={FORM_ID}
            variant="primary"
            disabled={updateCollection.isPending || !name.trim()}
            icon={updateCollection.isPending ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
          >
            저장
          </Button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={handleEdit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        <Field label="이름 *" error={isNameMissing ? '이름을 입력하세요.' : undefined}>
          {(id) => (
            <Input
              id={id}
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value)
                setIsNameMissing(false)
              }}
              placeholder="컬렉션 이름"
              required
            />
          )}
        </Field>

        <Field label="설명">
          {(id) => (
            <Textarea id={id} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="선택 사항" rows={3} />
          )}
        </Field>

        <Field label="기본 보안등급">
          {(id) => (
            <Select id={id} value={securityLevel} onChange={(e) => setSecurityLevel(e.target.value as '' | SecurityLevel)}>
              <option value="">지정 안 함 (공개)</option>
              {SECURITY_LEVELS.map((level) => (
                <option key={level} value={level}>{SECURITY_LEVEL_LABELS[level]}</option>
              ))}
            </Select>
          )}
        </Field>

        {!routeProjectId && (
          <Field
            label="프로젝트"
            hint="프로젝트를 지정하면 해당 프로젝트의 모든 멤버가 이 컬렉션에 자동으로 접근할 수 있습니다. 이미 프로젝트에 속한 컬렉션을 개인 컬렉션으로 되돌리는 것은 이 화면에서 지원하지 않습니다."
          >
            {(id) => (
              <Select id={id} value={projectId} onChange={(e) => setProjectId(e.target.value)}>
                <option value="">개인 컬렉션 (프로젝트 없음)</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </Select>
            )}
          </Field>
        )}

        <Field
          label="문서 처리 — 기본 워크플로우"
          hint={`이 컬렉션에 업로드되는 문서에 기본 적용될 전처리 워크플로우입니다.${collection.project_id ? '' : ' 개인 컬렉션은 프로젝트에 속한 커스텀 워크플로우를 가질 수 없어 시스템 기본값만 선택할 수 있습니다.'}`}
        >
          {(id) => (
            <Select
              id={id}
              value={workflowId}
              onChange={(e) => {
                setWorkflowId(e.target.value)
                setVersionMode('latest')
                setVersionNumber(null)
              }}
            >
              <option value="">표준 전처리 (시스템 기본값)</option>
              {(projectPreprocessWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                <option key={wf.id} value={wf.id}>{wf.name}</option>
              ))}
            </Select>
          )}
        </Field>

        {workflowId && (
          <VersionPicker
            idPrefix="edit"
            mode={versionMode}
            onModeChange={setVersionMode}
            versionNumber={versionNumber}
            onVersionChange={setVersionNumber}
            versions={publishedVersions}
          />
        )}

        {workflowId && previewGraph && previewGraph.blocks.length > 0 && (
          <Alert tone="info">{buildBlockChainPreview(previewGraph)}</Alert>
        )}

        <Field label="기본 분석 워크플로우" hint="지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다(요약·키워드 등이 문서에 자동 반영).">
          {(id) => (
            <Select
              id={id}
              value={analysisWorkflowId}
              onChange={(e) => {
                setAnalysisWorkflowId(e.target.value)
                setAnalysisVersionMode('latest')
                setAnalysisVersionNumber(null)
              }}
            >
              <option value="">자동 분석 안 함</option>
              {(projectAnalysisWorkflows?.items ?? []).map((wf) => (
                <option key={wf.id} value={wf.id}>{wf.name}</option>
              ))}
            </Select>
          )}
        </Field>

        {analysisWorkflowId && (
          <VersionPicker
            idPrefix="edit_analysis"
            mode={analysisVersionMode}
            onModeChange={setAnalysisVersionMode}
            versionNumber={analysisVersionNumber}
            onVersionChange={setAnalysisVersionNumber}
            versions={analysisPublishedVersions}
          />
        )}

        <SearchSettingsSection key={collection.id} collection={collection} />

        {updateCollection.isError && <Alert tone="danger">컬렉션 수정에 실패했습니다.</Alert>}
        {reprocessResult && <Alert tone="success">{reprocessResult}</Alert>}

        {reprocessConfirming ? (
          <Alert tone="danger">
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              <span>
                문서 {docCount}건을 현재 설정으로 다시 처리합니다. 예상 소요 시간은 약 {Math.max(1, Math.ceil(docCount * 0.5))}분입니다. 계속할까요?
              </span>
              <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
                <Button size="sm" variant="secondary" onClick={() => setReprocessConfirming(false)}>취소</Button>
                <Button size="sm" variant="danger" disabled={reprocessCollection.isPending} onClick={handleReprocess}>확인</Button>
              </div>
            </div>
          </Alert>
        ) : (
          <Button
            variant="secondary"
            isBlock
            disabled={reprocessCollection.isPending || docCount === 0}
            onClick={() => setReprocessConfirming(true)}
            icon={reprocessCollection.isPending ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
          >
            이 설정으로 다시 처리
          </Button>
        )}

        <Button variant="secondary" isBlock disabled={isExporting} onClick={handleExport}
          icon={isExporting ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
        >
          RAG 데이터 내보내기 (JSON)
        </Button>
      </form>
    </Modal>
  )
}
