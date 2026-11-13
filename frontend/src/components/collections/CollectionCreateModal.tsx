import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { useCreateCollection } from '../../hooks/useCollections'
import { useWorkflows } from '../../hooks/useWorkflows'
import { SECURITY_LEVELS, SECURITY_LEVEL_LABELS } from '../../hooks/useAccess'
import type { SecurityLevel } from '../../hooks/useDocumentMetadata'
import { Button, ErrorAlert, Field, Input, Modal, Select, Textarea } from '../ui'

export interface ProjectOption {
  id: string
  name: string
}

interface CollectionCreateModalProps {
  /** 쓸 수 있는 프로젝트 목록(소유자 또는 편집자) */
  projects: ProjectOption[]
  /** 프로젝트 화면 안에서 열렸으면 그 프로젝트 id. 프로젝트 선택은 숨긴다 */
  routeProjectId: string | undefined
  /** 처음 골라 둘 프로젝트 id. 빈 문자열이면 개인 컬렉션 */
  initialProjectId: string
  onClose: () => void
}

const FORM_ID = 'collection-create-form'

/** 새 컬렉션 만들기 창. 열릴 때마다 새로 마운트되므로 입력값은 열린 동안만 유지된다. */
export function CollectionCreateModal({ projects, routeProjectId, initialProjectId, onClose }: CollectionCreateModalProps) {
  const createCollection = useCreateCollection()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [projectId, setProjectId] = useState(initialProjectId)
  // '' = 표준 전처리(시스템 기본값) / 지정 안 함.
  const [workflowId, setWorkflowId] = useState('')
  const [analysisWorkflowId, setAnalysisWorkflowId] = useState('')
  const [securityLevel, setSecurityLevel] = useState<'' | SecurityLevel>('')
  const [isNameMissing, setIsNameMissing] = useState(false)
  const { data: preprocessWorkflows } = useWorkflows(projectId || null, 'PREPROCESS')
  const { data: analysisWorkflows } = useWorkflows(projectId || null, 'ANALYSIS')

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) {
      setIsNameMissing(true)
      return
    }
    setIsNameMissing(false)
    await createCollection.mutateAsync({
      name: name.trim(),
      description: description.trim() || undefined,
      project_id: projectId || undefined,
      default_workflow_id: workflowId || undefined,
      default_analysis_workflow_id: analysisWorkflowId || undefined,
    })
    onClose()
  }

  return (
    <Modal
      isOpen
      size="md"
      isDismissible={false}
      title="새 컬렉션 만들기"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>취소</Button>
          <Button
            type="submit"
            form={FORM_ID}
            variant="primary"
            disabled={createCollection.isPending || !name.trim()}
            icon={createCollection.isPending ? <Loader2 size={14} aria-hidden="true" style={{ animation: 'spin 1s linear infinite' }} /> : undefined}
          >
            만들기
          </Button>
        </>
      }
    >
      <form id={FORM_ID} onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
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

        <Field label="기본 보안등급" hint="문서에 보안등급을 따로 지정하지 않으면 이 등급이 적용됩니다. 사용자의 열람등급보다 높은 문서는 검색·채팅·목록에 나오지 않습니다.">
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
          <Field label="프로젝트" hint="프로젝트를 지정하면 해당 프로젝트의 모든 멤버가 이 컬렉션에 자동으로 접근할 수 있습니다.">
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

        <Field label="기본 전처리 워크플로우" hint="업로드되는 문서의 임베딩 모델·청킹 방식은 이 워크플로우의 문서분할·RAG저장 블록 설정을 따릅니다.">
          {(id) => (
            <Select id={id} value={workflowId} onChange={(e) => setWorkflowId(e.target.value)}>
              <option value="">표준 전처리 (시스템 기본값)</option>
              {(preprocessWorkflows?.items ?? []).filter((wf) => !wf.is_system_default).map((wf) => (
                <option key={wf.id} value={wf.id}>{wf.name}</option>
              ))}
            </Select>
          )}
        </Field>

        <Field label="기본 분석 워크플로우" hint="지정하면 전처리가 끝난 직후 이 워크플로우가 문서마다 자동으로 실행됩니다(요약·키워드 등이 문서에 자동 반영).">
          {(id) => (
            <Select id={id} value={analysisWorkflowId} onChange={(e) => setAnalysisWorkflowId(e.target.value)}>
              <option value="">자동 분석 안 함</option>
              {(analysisWorkflows?.items ?? []).map((wf) => (
                <option key={wf.id} value={wf.id}>{wf.name}</option>
              ))}
            </Select>
          )}
        </Field>

        {createCollection.isError && <ErrorAlert error={createCollection.error} message="컬렉션을 만들지 못했습니다." />}
      </form>
    </Modal>
  )
}
