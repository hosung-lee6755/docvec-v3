import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  useAddInquiryMessage,
  useDeleteInquiry,
  useUpdateInquiry,
  type InquiryCategory,
  type InquiryDetail,
  type InquiryStatus,
} from '../../hooks/useInquiries'
import { formatElapsed } from '../../lib/elapsedTime'
import { INQUIRY_CATEGORY_LABELS, INQUIRY_STATUS_LABELS } from '../../lib/inquiryLabels'
import { Badge, Button, Card, ErrorAlert, Field, Input, Select, Textarea } from '../ui'
import type { BadgeTone } from '../ui'

// 문의 상세: 문서 연결과 오류 기록, 메시지 주고받기, 작성자의 수정과 종료, 관리자의 상태 변경과 삭제.

const STATUS_TONE: Record<InquiryStatus, BadgeTone> = {
  open: 'info',
  in_progress: 'warning',
  resolved: 'success',
  closed: 'neutral',
}
const STATUSES = Object.keys(INQUIRY_STATUS_LABELS) as InquiryStatus[]
const CATEGORIES = Object.keys(INQUIRY_CATEGORY_LABELS) as InquiryCategory[]

interface InquiryDetailViewProps {
  inquiry: InquiryDetail
  isAdmin: boolean
  onDeleted: () => void
}

export function InquiryDetailView({ inquiry, isAdmin, onDeleted }: InquiryDetailViewProps) {
  const update = useUpdateInquiry(inquiry.id)
  const reply = useAddInquiryMessage(inquiry.id)
  const remove = useDeleteInquiry()
  const [replyBody, setReplyBody] = useState('')
  const [isEditing, setIsEditing] = useState(false)
  const firstMessage = inquiry.messages[0]
  const [draft, setDraft] = useState({ title: '', category: inquiry.category, body: '' })
  const mutationError = update.isError ? update.error : reply.isError ? reply.error : remove.isError ? remove.error : null

  const startEdit = () => {
    setDraft({ title: inquiry.title, category: inquiry.category, body: firstMessage?.body ?? '' })
    setIsEditing(true)
  }

  const saveEdit = () => {
    update.mutate(
      { title: draft.title.trim(), category: draft.category, body: draft.body.trim() },
      { onSuccess: () => setIsEditing(false) },
    )
  }

  const sendReply = () => {
    const body = replyBody.trim()
    if (!body) return
    reply.mutate({ body }, { onSuccess: () => setReplyBody('') })
  }

  const handleDelete = () => {
    if (!window.confirm('이 문의를 지울까요? 주고받은 메시지도 함께 지워지며 되돌릴 수 없습니다.')) return
    remove.mutate(inquiry.id, { onSuccess: onDeleted })
  }

  const canClose = inquiry.is_author && inquiry.status !== 'closed'
  const replyLabel = isAdmin && !inquiry.is_author ? '답변' : '추가 메시지'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
      {mutationError !== null && <ErrorAlert error={mutationError} message="요청을 처리하지 못했습니다." />}

      <Card title="문의 내용" actions={(
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
          {inquiry.can_edit && !isEditing && <Button size="sm" variant="secondary" onClick={startEdit}>수정</Button>}
          {canClose && <Button size="sm" variant="secondary" onClick={() => update.mutate({ status: 'closed' })}>종료</Button>}
          {inquiry.can_delete && <Button size="sm" variant="danger" onClick={handleDelete} disabled={remove.isPending}>삭제</Button>}
        </div>
      )}
      >
        <p className="ds-cell-sub" style={{ margin: 0 }}>
          {inquiry.author_name} · {formatElapsed(inquiry.created_at)} 작성 · 최근 활동 {formatElapsed(inquiry.updated_at)}
        </p>
        <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap', margin: 'var(--space-2) 0' }}>
          <Badge tone="outline">{INQUIRY_CATEGORY_LABELS[inquiry.category]}</Badge>
          <Badge tone={STATUS_TONE[inquiry.status]} hasDot>{INQUIRY_STATUS_LABELS[inquiry.status]}</Badge>
        </div>

        {isEditing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <Field label="분류">
              {(id) => (
                <Select id={id} value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value as InquiryCategory })}>
                  {CATEGORIES.map((value) => <option key={value} value={value}>{INQUIRY_CATEGORY_LABELS[value]}</option>)}
                </Select>
              )}
            </Field>
            <Field label="제목">
              {(id) => <Input id={id} value={draft.title} maxLength={200} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />}
            </Field>
            <Field label="내용">
              {(id) => <Textarea id={id} rows={6} value={draft.body} maxLength={5000} onChange={(e) => setDraft({ ...draft, body: e.target.value })} />}
            </Field>
            <div style={{ display: 'flex', gap: 'var(--space-2)', justifyContent: 'flex-end' }}>
              <Button variant="secondary" onClick={() => setIsEditing(false)}>취소</Button>
              <Button variant="primary" onClick={saveEdit} disabled={update.isPending || !draft.title.trim() || !draft.body.trim()}>저장</Button>
            </div>
          </div>
        ) : (
          <p style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{firstMessage?.body}</p>
        )}

        {inquiry.document && (
          <p style={{ margin: 'var(--space-3) 0 0' }}>
            연결된 문서: <Link to={`/documents/${inquiry.document.id}`}>{inquiry.document.original_filename}</Link>
          </p>
        )}
        {inquiry.error_snapshot && (
          <div style={{ marginTop: 'var(--space-3)' }}>
            <h2 style={{ fontSize: 'var(--text-sm)', fontWeight: 600, margin: '0 0 var(--space-2)' }}>문의 당시 오류 기록</h2>
            <pre style={{ fontSize: 'var(--text-xs)', whiteSpace: 'pre-wrap', wordBreak: 'break-all', margin: 0 }}>
              {inquiry.error_snapshot}
            </pre>
          </div>
        )}
      </Card>

      <Card title="주고받은 메시지">
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          {inquiry.messages.slice(1).map((message) => (
            <li key={message.id}>
              <p className="ds-cell-sub" style={{ margin: 0 }}>
                {message.is_admin ? <Badge tone="info">관리자</Badge> : null} {message.author_name} · {formatElapsed(message.created_at)}
              </p>
              <p style={{ whiteSpace: 'pre-wrap', margin: 'var(--space-1) 0 0' }}>{message.body}</p>
            </li>
          ))}
          {inquiry.messages.length <= 1 && <li className="ds-cell-sub">아직 주고받은 메시지가 없습니다.</li>}
        </ol>

        {inquiry.can_reply && (
          <div style={{ marginTop: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
            <Field label={replyLabel}>
              {(id) => <Textarea id={id} rows={4} value={replyBody} maxLength={5000} onChange={(e) => setReplyBody(e.target.value)} />}
            </Field>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button variant="primary" onClick={sendReply} disabled={reply.isPending || !replyBody.trim()}>
                {isAdmin && !inquiry.is_author ? '답변 보내기' : '메시지 보내기'}
              </Button>
            </div>
          </div>
        )}
      </Card>

      {isAdmin && (
        <Card title="관리">
          <Field label="상태" hint="상태를 바꾸면 작성자에게 알림이 갑니다.">
            {(id) => (
              <Select
                id={id}
                value={inquiry.status}
                disabled={update.isPending}
                onChange={(e) => update.mutate({ status: e.target.value as InquiryStatus })}
              >
                {STATUSES.map((value) => <option key={value} value={value}>{INQUIRY_STATUS_LABELS[value]}</option>)}
              </Select>
            )}
          </Field>
        </Card>
      )}
    </div>
  )
}
