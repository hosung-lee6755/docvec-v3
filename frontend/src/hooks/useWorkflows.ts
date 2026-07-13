import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../lib/apiClient'

export interface Workflow {
  id: string
  project_id: string
  name: string
  description: string | null
  status: 'DRAFT' | 'ACTIVE' | 'INACTIVE'
  created_at: string
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
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED' | 'CANCELLED'
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
}

export interface WorkflowRunStep {
  id: string
  block_instance_id: string
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  output: Record<string, unknown> | null
  error_message: string | null
}

export function useBlockTypes() {
  return useQuery<{ items: string[] }>({
    queryKey: ['block-types'],
    queryFn: async () => {
      const { data } = await apiClient.get('/workflows/block-types')
      return data
    },
    staleTime: Infinity,
  })
}

export function useWorkflows(projectId: string | null) {
  return useQuery<{ items: Workflow[] }>({
    queryKey: ['workflows', projectId],
    queryFn: async () => {
      const { data } = await apiClient.get('/workflows', { params: { project_id: projectId } })
      return data
    },
    enabled: !!projectId,
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
    mutationFn: async (input: { project_id: string; name: string; description?: string }) => {
      const { data } = await apiClient.post('/workflows', input)
      return data as Workflow
    },
    onSuccess: (workflow) => {
      queryClient.invalidateQueries({ queryKey: ['workflows', workflow.project_id] })
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
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['workflows', variables.projectId] })
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
      return data as { saved: boolean; validation_errors: string[] }
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
      return data as WorkflowRun
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
