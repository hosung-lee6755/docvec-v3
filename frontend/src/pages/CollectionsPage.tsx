import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { FolderOpen, FolderPlus } from 'lucide-react'
import {
  useCollections,
  useDeleteCollection,
  useEmbeddingModels,
  type Collection,
} from '../hooks/useCollections'
import { useProjects } from '../hooks/useProjects'
import { useAuthStore } from '../store/authStore'
import GoldenEvalModal from '../components/GoldenEvalModal'
import VectorStatsModal from '../components/VectorStatsModal'
import { CollectionsTable } from '../components/collections/CollectionsTable'
import { CollectionCreateModal } from '../components/collections/CollectionCreateModal'
import { CollectionEditModal } from '../components/collections/CollectionEditModal'
import { CollectionShareModal } from '../components/collections/CollectionShareModal'
import { Button, EmptyState, ErrorAlert, Page, PageBody, PageHeader, Spinner } from '../components/ui'

export default function CollectionsPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { projectId: routeProjectId } = useParams<{ projectId?: string }>()
  const { data, isLoading, isError, error, refetch } = useCollections(routeProjectId)
  const { data: projectsData } = useProjects()
  const { data: embeddingModels } = useEmbeddingModels()
  const deleteCollection = useDeleteCollection()
  const isAdmin = useAuthStore((s) => s.user?.role === 'admin')

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createSeedProjectId, setCreateSeedProjectId] = useState('')
  const [editTarget, setEditTarget] = useState<Collection | null>(null)
  const [shareTarget, setShareTarget] = useState<Collection | null>(null)
  const [goldenEvalCollection, setGoldenEvalCollection] = useState<Collection | null>(null)
  const [vectorStatsCollection, setVectorStatsCollection] = useState<Collection | null>(null)

  // Only projects where this user has editor+ access can receive a new/reassigned
  // collection (create_collection/update_collection enforce this server-side too).
  const editableProjects = (projectsData?.items ?? []).filter(
    (p) => p.is_owner || p.role === 'editor'
  )

  useEffect(() => {
    const state = location.state as { openCreate?: boolean; projectId?: string } | null
    if (state?.openCreate) {
      setIsCreateOpen(true)
      if (state.projectId) setCreateSeedProjectId(state.projectId)
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, navigate])

  useEffect(() => {
    if (routeProjectId) setCreateSeedProjectId(routeProjectId)
  }, [routeProjectId])

  const handleDelete = async (id: string) => {
    try {
      await deleteCollection.mutateAsync(id)
    } catch {
      // 실패 원인은 목록 위 알림이 보여 준다
    }
  }

  const items = data?.items ?? []

  return (
    <Page>
      <PageHeader
        title="컬렉션"
        subtitle="문서를 묶는 단위입니다. 검색과 채팅은 컬렉션을 기준으로 동작합니다."
        actions={<>
          <span className="ds-toolbar__meta">{`${items.length}개`}</span>
          <Button variant="primary" icon={<FolderPlus size={14} aria-hidden="true" />} onClick={() => setIsCreateOpen(true)}>
            새 컬렉션
          </Button>
        </>}
      />
      <PageBody>
        {deleteCollection.isError && <ErrorAlert error={deleteCollection.error} message="컬렉션을 삭제하지 못했습니다." />}
        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <Spinner />
          </div>
        )}

        {isError && <ErrorAlert error={error} message="컬렉션 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}

        {!isLoading && !isError && items.length === 0 && (
          <EmptyState
            icon={<FolderOpen size={40} aria-hidden="true" style={{ opacity: 0.4 }} />}
            title="컬렉션이 없습니다."
            description="새 컬렉션을 만들어 문서를 모아 보세요."
          />
        )}

        {!isLoading && !isError && items.length > 0 && (
          <CollectionsTable
            items={items}
            embeddingModels={embeddingModels?.items ?? []}
            isAdmin={isAdmin}
            isDeleting={deleteCollection.isPending}
            onOpenDocuments={(col) => navigate(
              `${routeProjectId ? `/projects/${routeProjectId}` : ''}/documents?collection=${col.id}`,
            )}
            onShare={setShareTarget}
            onEdit={setEditTarget}
            onGoldenEval={setGoldenEvalCollection}
            onVectorStats={setVectorStatsCollection}
            onDelete={handleDelete}
          />
        )}
      </PageBody>

      {isCreateOpen && (
        <CollectionCreateModal
          projects={editableProjects}
          routeProjectId={routeProjectId}
          initialProjectId={createSeedProjectId}
          onClose={() => setIsCreateOpen(false)}
        />
      )}

      {editTarget && (
        <CollectionEditModal
          key={editTarget.id}
          collection={editTarget}
          projects={editableProjects}
          routeProjectId={routeProjectId}
          onClose={() => setEditTarget(null)}
        />
      )}

      {shareTarget && (
        <CollectionShareModal
          key={shareTarget.id}
          collection={shareTarget}
          onClose={() => setShareTarget(null)}
        />
      )}

      {goldenEvalCollection && (
        <GoldenEvalModal
          collectionId={goldenEvalCollection.id}
          collectionName={goldenEvalCollection.name}
          onClose={() => setGoldenEvalCollection(null)}
        />
      )}

      {vectorStatsCollection && (
        <VectorStatsModal
          collectionId={vectorStatsCollection.id}
          collectionName={vectorStatsCollection.name}
          onClose={() => setVectorStatsCollection(null)}
        />
      )}
    </Page>
  )
}
