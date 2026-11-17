import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { useMessageFeedback, type ChatMessage, type FeedbackRating } from '../../hooks/useChat'
import { apiErrorDetail } from '../../lib/apiError'
import { Alert, Button, IconButton, Input } from '../ui'

const NOTE_MAX_LENGTH = 1000

// 답변 아래의 좋아요·싫어요. 같은 버튼을 다시 누르면 평가를 지운다.
// 싫어요를 고르면 무엇이 틀렸는지 한 줄 남길 수 있고, 관리자가 답변 추적 화면에서 모아 본다.
export function AnswerFeedback({ message }: { message: ChatMessage }) {
  const feedback = useMessageFeedback()
  const [note, setNote] = useState(message.feedback_note ?? '')
  const rating = message.feedback ?? null

  const rate = (next: FeedbackRating) => {
    const cleared = rating === next
    if (cleared) setNote('')
    feedback.mutate({ messageId: message.id, rating: cleared ? null : next, note: cleared ? null : note || null })
  }

  const saveNote = (e: React.FormEvent) => {
    e.preventDefault()
    feedback.mutate({ messageId: message.id, rating: 'down', note: note.trim() || null })
  }

  const isNoteSaved = (message.feedback_note ?? '') === note.trim()

  return (
    <div className="user-chat__feedback">
      <span className="user-chat__feedback-label">이 답변이 도움이 되었나요?</span>
      <IconButton
        label="도움이 됨"
        aria-pressed={rating === 'up'}
        className={rating === 'up' ? 'is-active' : undefined}
        onClick={() => rate('up')}
        disabled={feedback.isPending}
      >
        <ThumbsUp size={14} aria-hidden="true" />
      </IconButton>
      <IconButton
        label="도움이 안 됨"
        aria-pressed={rating === 'down'}
        className={rating === 'down' ? 'is-active' : undefined}
        onClick={() => rate('down')}
        disabled={feedback.isPending}
      >
        <ThumbsDown size={14} aria-hidden="true" />
      </IconButton>
      {rating === 'down' && (
        <form onSubmit={saveNote} className="user-chat__feedback-note">
          <Input
            type="text"
            aria-label="무엇이 틀렸는지"
            placeholder="무엇이 틀렸나요? (선택)"
            value={note}
            maxLength={NOTE_MAX_LENGTH}
            onChange={(e) => setNote(e.target.value)}
            controlSize="sm"
          />
          <Button type="submit" size="sm" variant="secondary" disabled={feedback.isPending || isNoteSaved}>
            {isNoteSaved && note ? '저장됨' : '남기기'}
          </Button>
        </form>
      )}
      {feedback.isError && <Alert tone="danger">{apiErrorDetail(feedback.error, '평가를 저장하지 못했습니다.')}</Alert>}
    </div>
  )
}
