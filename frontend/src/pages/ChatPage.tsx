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
import { DeepSearchProgress, DeepSearchSteps, DeepSearchToggle } from '../components/chat/DeepSearch'
import { CitationEvidence, LowOcrBadge } from '../components/chat/CitationEvidence'
import { Alert, Badge, Button, IconButton, Input, Page, PageTitle, Select, buttonClass } from '../components/ui'
import '../styles/screens/user.css'

export default function ChatPage() {
  const { conversationId, projectId } = useParams<{ conversationId: string; projectId?: string }>()
  const navigate = useNavigate()
  const basePath = projectId ? `/projects/${projectId}/chat` : '/chat'

  return (
    <Page className="user-chat">
      <div className="user-chat__layout">
        <ConversationSidebar
          projectId={projectId}
          activeId={conversationId ?? null}
          onSelect={(id) => navigate(`${basePath}/${id}`)}
          onNew={() => navigate(basePath)}
        />
        <div className="user-chat__main">
          {conversationId
            ? <ConversationView conversationId={conversationId} />
            : <NewConversationForm projectId={projectId} onCreated={(id) => navigate(`${basePath}/${id}`)} />}
        </div>
      </div>
    </Page>
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
    <div className="user-chat__list">
      <Button variant="primary" size="sm" isBlock onClick={onNew} icon={<Plus size={16} />}>
        새 채팅
      </Button>

      <div className="user-chat__list-items">
        {conversations?.map((c) => (
          <div
            key={c.id}
            onClick={() => editingId !== c.id && onSelect(c.id)}
            className={`user-chat__row chat-conv-row${c.id === activeId ? ' is-active' : ''}`}
          >
            {editingId === c.id ? (
              <>
                <Input
                  autoFocus
                  controlSize="sm"
                  value={editingTitle}
                  onChange={(e) => setEditingTitle(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitEdit()
                    if (e.key === 'Escape') setEditingId(null)
                  }}
                  onClick={(e) => e.stopPropagation()}
                  className="user-chat__rename"
                />
                <IconButton label="저장" onClick={(e) => { e.stopPropagation(); commitEdit() }}>
                  <Check size={14} />
                </IconButton>
                <IconButton label="취소" onClick={(e) => { e.stopPropagation(); setEditingId(null) }}>
                  <X size={14} />
                </IconButton>
              </>
            ) : (
              <>
                {/* 키보드와 화면 낭독기가 대화를 고를 수 있게 제목을 단추로 둔다. */}
                <button
                  type="button"
                  className="user-chat__row-title"
                  aria-current={c.id === activeId ? 'page' : undefined}
                  onClick={(e) => { e.stopPropagation(); onSelect(c.id) }}
                >
                  {c.title}
                </button>
                <IconButton label="이름 변경" onClick={(e) => { e.stopPropagation(); startEdit(c) }}>
                  <Pencil size={13} />
                </IconButton>
                <IconButton label="삭제" tone="danger" onClick={(e) => { e.stopPropagation(); handleDelete(c.id) }}>
                  <Trash2 size={13} />
                </IconButton>
              </>
            )}
          </div>
        ))}
        {!conversations?.length && (
          <p className="user-chat__empty">아직 채팅이 없습니다.</p>
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
  const [isDeep, setIsDeep] = useState(false)

  const models = modelsData?.items ?? []
  const selectedModel = models.find((m) => m.key === modelKey) ?? models[0]

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    const model = modelKey || models[0]?.key
    if (!trimmed || !model) return
    createConversation.mutate(
      {
        query: trimmed, project_id: projectId || undefined, collection_id: collectionId || undefined, model_key: model,
        mode: isDeep ? 'deep' : 'standard',
      },
      { onSuccess: (data) => onCreated(data.id) }
    )
  }

  return (
    <div className="user-chat__start">
      <PageTitle className="user-chat__start-title">새 채팅 시작</PageTitle>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        <div className="user-chat__controls">
          <Select
            controlSize="sm"
            value={collectionId}
            onChange={(e) => setCollectionId(e.target.value)}
            className="user-chat__select user-chat__select--collection"
          >
            <option value="">전체 문서</option>
            {collectionsData?.items.map((col) => (
              <option key={col.id} value={col.id}>{col.name}</option>
            ))}
          </Select>

          <Select
            controlSize="sm"
            value={modelKey || models[0]?.key || ''}
            onChange={(e) => setModelKey(e.target.value)}
            className="user-chat__select user-chat__select--model"
          >
            {models.map((m) => (
              <option key={m.key} value={m.key} disabled={!m.available}>
                {m.label}{!m.available ? ' (API 키 필요)' : ''}
              </option>
            ))}
          </Select>

          <DeepSearchToggle checked={isDeep} onChange={setIsDeep} />

          {selectedModel && !selectedModel.available && (
            <Link to="/settings" className={buttonClass('ghost', 'sm')}>
              <SettingsIcon size={14} /> API 키 등록하러 가기
            </Link>
          )}
        </div>

        <div className="user-chat__form-row">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="문서 내용에 대해 질문하세요..."
            controlSize="sm"
            className="user-chat__grow"
          />
          <Button
            type="submit"
            variant="primary"
            size="sm"
            disabled={createConversation.isPending || !query.trim() || !selectedModel?.available}
          >
            {createConversation.isPending
              ? <span className="user-spinner" role="status"><span className="sr-only">생성 중</span></span>
              : <Send size={16} />}
            질문
          </Button>
        </div>
        {selectedModel?.backend === 'local' && (
          <p className="user-chat__hint">
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
  const [isDeep, setIsDeep] = useState(false)

  const messages = conversation?.messages ?? []
  const lastMessage = messages[messages.length - 1]
  const isBusy = lastMessage
    ? lastMessage.status === 'PENDING' || lastMessage.status === 'GENERATING'
    : sendMessage.isPending

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = query.trim()
    if (!trimmed || isBusy) return
    sendMessage.mutate({ query: trimmed, mode: isDeep ? 'deep' : 'standard' })
    setQuery('')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: '1 1 auto', minHeight: 0 }}>
      <div className="user-chat__thread">
        {messages.map((m) => <ChatMessageBubble key={m.id} message={m} />)}
      </div>

      <form onSubmit={handleSubmit} className="user-chat__composer">
        <DeepSearchToggle checked={isDeep} onChange={setIsDeep} disabled={isBusy} />
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="이어서 질문하세요..."
          controlSize="sm"
          className="user-chat__grow"
        />
        <Button type="submit" variant="primary" size="sm" disabled={isBusy || !query.trim()}>
          {isBusy
            ? <span className="user-spinner" role="status"><span className="sr-only">생성 중</span></span>
            : <Send size={16} />}
          질문
        </Button>
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
            className="user-chat__cite-btn"
          >
            {idx}
          </button>
        )
      }
      return <span key={i}>{part}</span>
    })

  return (
    <div className="user-chat__turn">
      <div className="user-chat__bubble">
        <p className="user-chat__label">
          질문
          {chat.mode === 'deep' && <Badge tone="neutral">심층 검색</Badge>}
        </p>
        <p style={{ margin: 0 }}>{chat.query}</p>
      </div>

      {(chat.status === 'PENDING' || chat.status === 'GENERATING') && (
        chat.partial_answer ? (
          <div className="user-chat__bubble user-chat__bubble--answer">
            <p className="user-chat__label">
              답변
              <span className="user-spinner" role="status" style={{ width: 12, height: 12 }}>
                <span className="sr-only">생성 중</span>
              </span>
            </p>
            <p className="user-chat__text">
              {chat.partial_answer}
              <span className="user-chat__cursor">▌</span>
            </p>
          </div>
        ) : chat.mode === 'deep' ? (
          <DeepSearchProgress progress={chat.progress} />
        ) : (
          <div className="user-chat__waiting">
            <div className="user-spinner" role="status"><span className="sr-only">생성 중</span></div>
            답변 생성 중...
          </div>
        )
      )}

      {chat.status === 'FAILED' && (
        <Alert tone="danger">
          답변 생성에 실패했습니다{chat.error_message ? `: ${chat.error_message}` : ''}
        </Alert>
      )}

      {chat.status === 'DONE' && (
        <>
          <div className="user-chat__bubble user-chat__bubble--answer">
            <p className="user-chat__label">
              답변
              <Badge tone="info" hasDot>AI가 생성한 답변</Badge>
            </p>
            <p className="user-chat__text">
              {chat.answer ? renderAnswer(chat.answer) : null}
            </p>
          </div>

          {!!chat.expanded_terms?.length && (
            <p className="user-chat__notice">
              사전의 동의어로 함께 찾은 낱말: {chat.expanded_terms.join(', ')}
            </p>
          )}

          {chat.agent_steps && <DeepSearchSteps steps={chat.agent_steps} />}

          {!!chat.citations?.length && (
            <div>
              <Button
                variant="ghost"
                size="sm"
                className="user-chat__cite-toggle"
                onClick={() => setCitationsOpen((v) => !v)}
                aria-expanded={citationsOpen}
                icon={citationsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              >
                인용된 발췌문 ({chat.citations.length})
              </Button>
              {citationsOpen && (
                <div className="user-chat__cite-list">
                  {chat.citations.map((c) => c.hidden ? (
                    <div
                      key={c.index}
                      ref={(el) => { citationRefs.current[c.index] = el }}
                      className="user-chat__cite is-hidden"
                    >
                      <span className="user-chat__cite-index">[{c.index}]</span> 열람 권한이 없는 문서입니다. 답변 이후 권한이 바뀌었거나 문서가 삭제됐습니다.
                    </div>
                  ) : (
                    <div
                      key={c.index}
                      ref={(el) => { citationRefs.current[c.index] = el }}
                      className={`user-chat__cite${flashIndex === c.index ? ' is-flash' : ''}`}
                    >
                      <div className="user-chat__cite-meta">
                        <span className="user-chat__cite-index">[{c.index}]</span>
                        {c.collection_name && (
                          <span className="user-chat__cite-file">
                            <FolderOpen size={12} />
                            {c.collection_name}
                          </span>
                        )}
                        <span className="user-chat__cite-file">
                          <FileText size={12} />
                          {c.filename ?? '문서'}
                        </span>
                        {c.page_number ? <span>{c.page_number}쪽</span> : null}
                        <LowOcrBadge evidence={c.evidence} />
                        <span className="user-chat__spacer" />
                        {c.document_id && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => window.open(`/documents/${c.document_id}`, '_blank', 'noopener')}
                          >
                            문서 열기
                          </Button>
                        )}
                      </div>
                      <p className="user-chat__cite-text">{c.text}</p>
                      <CitationEvidence evidence={c.evidence} />
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
