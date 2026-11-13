import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'
import type { JsonSchema } from '../lib/blockConfigSchema'

export interface Workflow {
  id: string
  project_id: string | null
  name: string
  description: string | null
  status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'
  kind: 'PREPROCESS' | 'ANALYSIS'
  created_at: string
}

export interface WorkflowListItem extends Workflow {
  updated_at: string
  created_by_username: string | null
  is_system_default: boolean
  default_for_collection_count: number
  latest_version_number: number | null
  project_name: string | null
}

export interface WorkflowVersion {
  id: string
  workflow_id: string
  version_number: number
  published_at: string | null
  created_at: string
}

export interface WorkflowBlock {
  id: string
  block_type: string
  label: string | null
  position: { x: number; y: number } | Record<string, never>
  config: Record<string, unknown>
}

export interface WorkflowEdge {
  id: string
  from_block_id: string
  to_block_id: string
  condition: Record<string, unknown> | null
}

export interface WorkflowGraph {
  blocks: WorkflowBlock[]
  edges: WorkflowEdge[]
}

export interface WorkflowRun {
  id: string
  version_id: string
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'WAITING_REVIEW'
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
  // Enriched by GET /{workflow_id}/runs (absent on the run-detail endpoint).
  version_number?: number
  document_id?: string | null
  collection_id?: string | null
  document_filename?: string | null
}

export interface WorkflowRunStep {
  id: string
  block_instance_id: string
  block_type: string | null
  label: string | null
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'SKIPPED'
  output: Record<string, unknown> | null
  error_message: string | null
  cached: boolean
  warnings: string[] | null
}

export interface BlockTypeInfo {
  block_type: string
  block_version: number
  category: string
  label: string
  config_schema: JsonSchema
}

export function useBlockTypes() {
  return useQuery<{ items: BlockTypeInfo[] }>({
    queryKey: ['block-types'],
    queryFn: async () => {
      const { data } = await apiClient.get('/workflows/block-types')
      return data
    },
    staleTime: Infinity,
  })
}

export function useWorkflows(projectId: string | null, kind?: 'PREPROCESS' | 'ANALYSIS') {
  return useQuery<{ items: WorkflowListItem[] }>({
    queryKey: ['workflows', projectId, kind ?? null],
    queryFn: async () => {
      const { data } = await apiClient.get('/workflows', {
        params: { project_id: projectId ?? undefined, kind },
      })
      return data
    },
  })
}

// PATCH /workflows/{id}를 name 필드로 호출해 워크플로우 이름을 변경한다.
export function useRenameWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ workflowId, name }: { workflowId: string; name: string; projectId: string }) => {
      const { data } = await apiClient.patch(`/workflows/${workflowId}`, { name })
      return data as Workflow
    },
    onSuccess: () => {
      // 정확한 ['workflows', projectId, kind] 키만 무효화하면 전역(/workflows,
      // 프로젝트 없음) 목록의 캐시 키(['workflows', null, kind])와 불일치해
      // 갱신되지 않는다 — prefix 매칭되도록 'workflows' 하나만 남겨 모든 스코프를 덮는다.
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })
}

export function useUpdateWorkflowStatus() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (
      { workflowId, status }: { workflowId: string; status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'; projectId: string },
    ) => {
      const { data } = await apiClient.patch(`/workflows/${workflowId}`, { status })
      return data as Workflow
    },
    onSuccess: () => {
      // 정확한 ['workflows', projectId, kind] 키만 무효화하면 전역(/workflows,
      // 프로젝트 없음) 목록의 캐시 키(['workflows', null, kind])와 불일치해
      // 갱신되지 않는다 — prefix 매칭되도록 'workflows' 하나만 남겨 모든 스코프를 덮는다.
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })
}

export function useDuplicateWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (
      { workflowId, projectId }: { workflowId: string; projectId: string },
    ) => {
      const { data } = await apiClient.post(`/workflows/${workflowId}/duplicate`, { project_id: projectId })
      return data as Workflow
    },
    onSuccess: () => {
      // 정확한 ['workflows', projectId, kind] 키만 무효화하면 전역(/workflows,
      // 프로젝트 없음) 목록의 캐시 키(['workflows', null, kind])와 불일치해
      // 갱신되지 않는다 — prefix 매칭되도록 'workflows' 하나만 남겨 모든 스코프를 덮는다.
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })
}

export function useWorkflow(workflowId: string | null) {
  return useQuery<Workflow>({
    queryKey: ['workflow', workflowId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/workflows/${workflowId}`)
      return data
    },
    enabled: !!workflowId,
  })
}

export function useCreateWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (
      input: { project_id: string; name: string; description?: string; kind?: 'PREPROCESS' | 'ANALYSIS' },
    ) => {
      const { data } = await apiClient.post('/workflows', input)
      return data as Workflow
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })
}

export function useDeleteWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ workflowId }: { workflowId: string; projectId: string }) => {
      const { data } = await apiClient.delete(`/workflows/${workflowId}`)
      return data as { deleted: boolean }
    },
    onSuccess: () => {
      // 정확한 ['workflows', projectId, kind] 키만 무효화하면 전역(/workflows,
      // 프로젝트 없음) 목록의 캐시 키(['workflows', null, kind])와 불일치해
      // 갱신되지 않는다 — prefix 매칭되도록 'workflows' 하나만 남겨 모든 스코프를 덮는다.
      queryClient.invalidateQueries({ queryKey: ['workflows'] })
    },
  })
}

export function useWorkflowVersions(workflowId: string | null) {
  return useQuery<{ items: WorkflowVersion[] }>({
    queryKey: ['workflow-versions', workflowId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/workflows/${workflowId}/versions`)
      return data
    },
    enabled: !!workflowId,
  })
}

export function useCreateDraftVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (workflowId: string) => {
      const { data } = await apiClient.post(`/workflows/${workflowId}/versions`)
      return data as WorkflowVersion
    },
    onSuccess: (version) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-versions', version.workflow_id] })
    },
  })
}

export function useDeleteVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ workflowId, versionId }: { workflowId: string; versionId: string }) => {
      const { data } = await apiClient.delete(`/workflows/${workflowId}/versions/${versionId}`)
      return data as { deleted: boolean }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-versions', variables.workflowId] })
    },
  })
}

export function useWorkflowGraph(workflowId: string | null, versionId: string | null) {
  return useQuery<WorkflowGraph>({
    queryKey: ['workflow-graph', workflowId, versionId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/workflows/${workflowId}/versions/${versionId}/graph`)
      return data
    },
    enabled: !!workflowId && !!versionId,
  })
}

export interface GraphValidationError {
  message: string
  block_id: string | null
}

export function useSaveWorkflowGraph() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      workflowId, versionId, graph,
    }: { workflowId: string; versionId: string; graph: WorkflowGraph }) => {
      const { data } = await apiClient.put(
        `/workflows/${workflowId}/versions/${versionId}/graph`,
        graph,
      )
      return data as { saved: boolean; validation_errors: GraphValidationError[] }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({
        queryKey: ['workflow-graph', variables.workflowId, variables.versionId],
      })
    },
  })
}

export function usePublishVersion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ workflowId, versionId }: { workflowId: string; versionId: string }) => {
      const { data } = await apiClient.post(
        `/workflows/${workflowId}/versions/${versionId}/publish`,
      )
      return data as { message: string; version_number: number }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-versions', variables.workflowId] })
      queryClient.invalidateQueries({ queryKey: ['workflow', variables.workflowId] })
    },
  })
}

export function useRunWorkflow() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      workflowId, versionId, documentId, collectionId,
    }: { workflowId: string; versionId: string; documentId?: string; collectionId?: string }) => {
      const { data } = await apiClient.post(`/workflows/${workflowId}/run`, {
        version_id: versionId,
        document_id: documentId,
        collection_id: collectionId,
      })
      // One run per target document — a collection target fans out into
      // multiple runs (items.length > 1).
      return data as { items: WorkflowRun[]; count: number; skipped_in_progress?: number }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-runs', variables.workflowId] })
    },
  })
}

export function useDeleteRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ runId }: { workflowId: string; runId: string }) => {
      const { data } = await apiClient.delete(`/workflows/runs/${runId}`)
      return data as { deleted: boolean }
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-runs', variables.workflowId] })
    },
  })
}

export function useWorkflowRuns(workflowId: string | null) {
  return useQuery<{ items: WorkflowRun[] }>({
    queryKey: ['workflow-runs', workflowId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/workflows/${workflowId}/runs`)
      return data
    },
    enabled: !!workflowId,
    refetchInterval: (query) => {
      const items = query.state.data?.items ?? []
      const isActive = items.some((r) => r.status === 'QUEUED' || r.status === 'RUNNING')
      return isActive ? 2000 : false
    },
  })
}

export function useWorkflowRun(runId: string | null) {
  return useQuery<{ run: WorkflowRun; steps: WorkflowRunStep[] }>({
    queryKey: ['workflow-run', runId],
    queryFn: async () => {
      const { data } = await apiClient.get(`/workflows/runs/${runId}`)
      return data
    },
    enabled: !!runId,
    refetchInterval: (query) => {
      const status = query.state.data?.run.status
      return status === 'QUEUED' || status === 'RUNNING' ? 2000 : false
    },
  })
}

export function useResumeRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => {
      const { data } = await apiClient.post(`/workflows/runs/${runId}/resume`)
      return data
    },
    onSuccess: (_data, runId) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-run', runId] })
      // doc.status/isWaitingReview, useDocumentRuns, useDocumentQuality all
      // key off ['documents', ...] — without this the approval banner and
      // quality tab keep showing the stale WAITING_REVIEW state after resume.
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}

export function useCancelRun() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (runId: string) => {
      const { data } = await apiClient.post(`/workflows/runs/${runId}/cancel`)
      return data
    },
    onSuccess: (_data, runId) => {
      queryClient.invalidateQueries({ queryKey: ['workflow-run', runId] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })
}
