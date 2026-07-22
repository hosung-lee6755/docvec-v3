import { useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Send, FileText, Settings as SettingsIcon, Plus, Pencil, Trash2, Check, X, ChevronDown, ChevronUp, FolderOpen } from 'lucide-react'
import { Link } from 'react-router-dom'
import { useCollections } from '../hooks/useCollections'
import {
  useChatModels,
  useConversations,
  useConversation,
  useCreateConversation,
  useSendMessage,
  useRenameConversation,
  useDeleteConversation,
  type ChatMessage,
  type ConversationSummary,
} from '../hooks/useChat'

export default function ChatPage() {
  const { conversationId, projectId } = useParams<{ conversationId: string; projectId?: string }>()
  const navigate = useNavigate()
  const basePath = projectId ? `/projects/${projectId}/chat` : '/chat'

  return (
    <div style={{ display: 'flex', gap: 'var(--space-6)', height: 'calc(100vh - var(--space-8) * 2)' }}>
      <ConversationSidebar
        projectId={projectId}
        activeId={conversationId ?? null}
        onSelect={(id) => navigate(`${basePath}/${id}`)}
        onNew={() => navigate(basePath)}
      />
      <div style={{ flex: '1 1 auto', minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {conversationId
          ? <ConversationView conversationId={conversationId} />
          : <NewConversationForm projectId={projectId} onCreated={(id) => navigate(`${basePath}/${id}`)} />}
      </div>
    </div>
  )
}

function ConversationSidebar({
  projectId, activeId, onSelect, onNew,
}: { projectId?: string; activeId: string | null; onSelect: (id: string) => void; onNew: () => void }) {
  const { data: conversations } = useConversations(projectId)
  const renameConv = useRenameConversation()
  const deleteConv = useDeleteConversation()
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState('')

  const startEdit = (c: ConversationSummary) => {
    setEditingId(c.id)
    setEditingTitle(c.title)
  }
  const commitEdit = () => {
    const title = editingTitle.trim()
    if (editingId && title) renameConv.mutate({ id: editingId, title })
    setEditingId(null)
  }
  const handleDelete = (id: string) => {
    if (!window.confirm('이 채팅을 삭제할까요? 대화 내용이 모두 사라집니다.')) return
    deleteConv.mutate(id)
    if (id === activeId) onNew()
  }

  return (
    <div style={{
      width: 260, flexShrink: 0, display: 'flex', flexDirection: 'column',
      borderRight: '1px solid var(--color-border)', paddingRight: 'var(--space-4)',
    }}>
      <button type="button" onClick={onNew} className="krds-btn small primary"
        style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', marginBottom: 'var(--space-4)' }}>
        <Plus size={16} /> 새 채팅
      </button>

      <div style={{ flex: '1 1 auto', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 2 }}>
        {conversations?.map((c) => (
          <div
            key={c.id}
            onClick={() => editingId !== c.id && onSelect(c.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 'var(--space-2)',
              padding: 'var(--space-2) var(--space-3)', borderRadius: 'var(--radius-md, 8px)',
              cursor: 'pointer', background: c.id === activeId ? '#eff6ff' : 'transparent',
              color: c.id === activeId ? '#1d4ed8' : '#334155', fontSize: 13,
            }}
            className="chat-conv-row"
          >
            {editingId === c.id ? (
              <>
                <input
                  autoFocus
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitEdit()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="krds-input small"
                  style={{ flex: '1 1 auto', minWidth: 0 }}
                />
                <button type="button" onClick={(e) => { e.stopPropagation(); commitEdit() }}
                  className="krds-btn text xsmall icon-btn success" title="저장">
                  <Check size={14} />
                </button>
                <button type="button" onClick={(e) => { e.stopPropagation(); setEditingId(null) }}
                  className="krds-btn text xsmall icon-btn" title="취소">
                  <X size={14} />
                </button>
              </>
            ) : (
              <>
                <span style={{ flex: '1 1 auto', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {c.title}
                </span>
                <button type="button" onClick={(e) => { e.stopPropagation(); startEdit(c) }}
                  className="krds-btn text xsmall icon-btn" title="이름 변경">
                  <Pencil size={13} />
                </button>
                <button type="button" onClick={(e) => { e.stopPropagation(); handleDelete(c.id) }}
                  className="krds-btn text xsmall icon-btn" title="삭제">
                  <Trash2 size={13} />
                </button>
              </>
            )}
          </div>
        ))}
        {!conversations?.length && (
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', padding: 'var(--space-3)' }}>
            아직 채팅이 없습니다.
          </p>
        )}
      </div>
    </div>
  )
}

function NewConversationForm({ projectId, onCreated }: { projectId?: string; onCreated: (id: string) => void }) {
  const { data: collectionsData } = useCollections(projectId)
  const { data: modelsData } = useChatModels(projectId)
  const createConversation = useCreateConversation()

  const [collectionId, setCollectionId] = useState('')
  const [modelKey, setModelKey] = useState('')
  const [query, setQuery] = useState('')

  const models = modelsData?.items ?? []
  const selectedModel = models.find((m) => m.key === modelKey) ?? models[0]

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    const model = modelKey || models[0]?.key
    if (!trimmed || !model) return
    createConversation.mutate(
      { query: trimmed, project_id: projectId || undefined, collection_id: collectionId || undefined, model_key: model },
      { onSuccess: (data) => onCreated(data.id) }
    )
  }

  return (
    <div style={{ flex: '1 1 auto', display: 'flex', flexDirection: 'column', justifyContent: 'center', maxWidth: 640, margin: '0 auto', width: '100%' }}>
      <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 'var(--space-6)', textAlign: 'center' }}>새 채팅 시작</h1>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div style={{ display: 'flex', flexDirection: 'row', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-2)' }}>
          <select
            value={collectionId}
            onChange={(e) => setCollectionId(e.target.value)}
            className="krds-form-select small"
            style={{ flex: '0 0 180px', width: 180 }}
          >
            <option value="">전체 문서</option>
            {collectionsData?.items.map((col) => (
              <option key={col.id} value={col.id}>{col.name}</option>
            ))}
          </select>

          <select
            value={modelKey || models[0]?.key || ''}
            onChange={(e) => setModelKey(e.target.value)}
            className="krds-form-select small"
            style={{ flex: '0 0 240px', width: 240 }}
          >
            {models.map((m) => (
              <option key={m.key} value={m.key} disabled={!m.available}>
                {m.label}{!m.available ? ' (API 키 필요)' : ''}
              </option>
            ))}
          </select>

          {selectedModel && !selectedModel.available && (
            <Link to="/settings" className="krds-btn text small">
              <SettingsIcon size={14} /> API 키 등록하러 가기
            </Link>
          )}
        </div>

        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="문서 내용에 대해 질문하세요..."
            className="krds-input small"
            style={{ flex: '1 1 auto', width: '100%' }}
          />
          <button
            type="submit"
            disabled={createConversation.isPending || !query.trim() || !selectedModel?.available}
            className="krds-btn small primary"
          >
            {createConversation.isPending
              ? <div className="krds-spinner" role="status" style={{ width: 16, height: 16 }}><span className="sr-only">생성 중</span></div>
              : <Send size={16} />}
            질문
          </button>
        </div>
        {selectedModel?.backend === 'local' && (
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0, textAlign: 'center' }}>
            로컬 모델은 첫 요청 시 모델 로딩으로 응답이 오래 걸릴 수 있습니다.
          </p>
        )}
      </form>
    </div>
  )
}

function ConversationView({ conversationId }: { conversationId: string }) {
  const { data: conversation } = useConversation(conversationId)
  const sendMessage = useSendMessage(conversationId)
  const [query, setQuery] = useState('')

  const messages = conversation?.messages ?? []
  const lastMessage = messages[messages.length - 1]
  const isBusy = lastMessage
    ? lastMessage.status === 'PENDING' || lastMessage.status === 'GENERATING'
    : sendMessage.isPending

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || isBusy) return
    sendMessage.mutate(trimmed)
    setQuery('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0 }}>
      <div style={{ flex: '1 1 auto', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 'var(--space-6)', paddingBottom: 'var(--space-4)' }}>
        {messages.map((m) => <ChatMessageBubble key={m.id} message={m} />)}
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 'var(--space-3)', paddingTop: 'var(--space-4)', borderTop: '1px solid var(--color-border)' }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="이어서 질문하세요..."
          className="krds-input small"
          style={{ flex: '1 1 auto', width: '100%' }}
        />
        <button type="submit" disabled={isBusy || !query.trim()} className="krds-btn small primary">
          {isBusy
            ? <div className="krds-spinner" role="status" style={{ width: 16, height: 16 }}><span className="sr-only">생성 중</span></div>
            : <Send size={16} />}
          질문
        </button>
      </form>
    </div>
  )
}

const _CITATION_TOKEN_RE = /(\[\d+\])/g

function ChatMessageBubble({ message: chat }: { message: ChatMessage }) {
  const [citationsOpen, setCitationsOpen] = useState(true)
  const [flashIndex, setFlashIndex] = useState<number | null>(null)
  const citationRefs = useRef<Record<number, HTMLDivElement | null>>({})

  const jumpToCitation = (index: number) => {
    setCitationsOpen(true)
    // Panel may need a render pass to open before the target exists to scroll to.
    setTimeout(() => {
      citationRefs.current[index]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setFlashIndex(index)
      setTimeout(() => setFlashIndex(null), 1600)
    }, 50)
  }

  const citationIndices = new Set((chat.citations ?? []).map((c) => c.index))

  const renderAnswer = (text: string) =>
    text.split(_CITATION_TOKEN_RE).map((part, i) => {
      const m = /^\[(\d+)\]$/.exec(part)
      const idx = m ? Number(m[1]) : null
      if (idx !== null && citationIndices.has(idx)) {
        return (
          <button
            key={i}
            type="button"
            onClick={() => jumpToCitation(idx)}
            title={`발췌문 [${idx}] 보기`}
            style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              background: '#dbeafe', color: '#1d4ed8', border: 'none', borderRadius: 4,
              fontSize: 11, fontWeight: 700, padding: '0 5px', margin: '0 1px',
              cursor: 'pointer', verticalAlign: 'baseline', lineHeight: '18px',
            }}
          >
            {idx}
          </button>
        )
      }
      return <span key={i}>{part}</span>
    })

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      <div style={{
        background: '#fff', border: '1px solid #e2e8f0',
        borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
      }}>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)' }}>질문</p>
        <p style={{ margin: 0 }}>{chat.query}</p>
      </div>

      {(chat.status === 'PENDING' || chat.status === 'GENERATING') && (
        chat.partial_answer ? (
          <div style={{
            background: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          }}>
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)', display: 'flex', alignItems: 'center', gap: 8 }}>
              답변
              <span className="krds-spinner" role="status" style={{ width: 12, height: 12 }}>
                <span className="sr-only">생성 중</span>
              </span>
            </p>
            <p style={{ margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {chat.partial_answer}
              <span style={{ opacity: 0.5 }}>▌</span>
            </p>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', padding: 'var(--space-4)', color: 'var(--color-text-muted)' }}>
            <div className="krds-spinner" role="status"><span className="sr-only">생성 중</span></div>
            답변 생성 중...
          </div>
        )
      )}

      {chat.status === 'FAILED' && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius-md)', padding: 'var(--space-4)', color: '#dc2626',
        }}>
          답변 생성에 실패했습니다{chat.error_message ? `: ${chat.error_message}` : ''}
        </div>
      )}

      {chat.status === 'DONE' && (
        <>
          <div style={{
            background: '#eff6ff', border: '1px solid #bfdbfe',
            borderRadius: 'var(--radius-md)', padding: 'var(--space-4)',
          }}>
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 var(--space-2)' }}>답변</p>
            <p style={{ margin: 0, whiteSpace: 'pre-wrap', lineHeight: 1.6 }}>
              {chat.answer ? renderAnswer(chat.answer) : null}
            </p>
          </div>

          {!!chat.citations?.length && (
            <div>
              <button
                type="button"
                onClick={() => setCitationsOpen((v) => !v)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 'var(--space-1)',
                  background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                  fontSize: 13, fontWeight: 600, margin: '0 0 var(--space-2)', color: 'inherit',
                }}
                aria-expanded={citationsOpen}
              >
                {citationsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                인용된 발췌문 ({chat.citations.length})
              </button>
              {citationsOpen && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
                  {chat.citations.map((c) => (
                    <div
                      key={c.index}
                      ref={(el) => { citationRefs.current[c.index] = el }}
                      style={{
                        background: flashIndex === c.index ? '#fef9c3' : '#fff',
                        border: flashIndex === c.index ? '1px solid #facc15' : '1px solid #e2e8f0',
                        borderRadius: 'var(--radius-md)', padding: 'var(--space-3)',
                        transition: 'background-color .4s ease, border-color .4s ease',
                      }}
                    >
                      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 'var(--space-3)', marginBottom: 'var(--space-1)', fontSize: 12, color: 'var(--color-text-muted)' }}>
                        <span style={{ fontWeight: 600 }}>[{c.index}]</span>
                        {c.collection_name && (
                          <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                            <FolderOpen size={12} />
                            {c.collection_name}
                          </span>
                        )}
                        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <FileText size={12} />
                          {c.filename ?? '문서'}
                        </span>
                        {c.page_number ? <span>{c.page_number}쪽</span> : null}
                        <span style={{ flex: 1 }} />
                        {c.document_id && (
                          <button
                            type="button"
                            onClick={() => window.open(`/documents/${c.document_id}`, '_blank', 'noopener')}
                            className="krds-btn text small"
                            style={{ cursor: 'pointer', fontSize: 12 }}
                          >
                            문서 열기
                          </button>
                        )}
                      </div>
                      <p style={{ margin: 0, fontSize: 13, lineHeight: 1.5 }}>{c.text}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
