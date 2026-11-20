import { useState } from 'react'
import { ThumbsDown, ThumbsUp } from 'lucide-react'
import { useMessageFeedback, type ChatMessage, type FeedbackRating } from '../../hooks/useChat'
import { apiErrorDetail } from '../../lib/apiError'
import { Alert, Button, IconButton, Input } from '../ui'

const NOTE_MAX_LENGTH = 1000

// 답변 아래의 좋아요·싫어요. 같은 버튼을 다시 누르면 평가를 지운다.
// 누르는 즉시 눌린 상태를 보여 주고, 저장에 실패하면 되돌린다(2026-11-20, 반응이 없어 두 번 누르던 문제).
// 싫어요를 고르면 무엇이 틀렸는지 한 줄 남길 수 있고, 칸에서 벗어나면 저장된다. 관리자는 답변 추적 화면에서 모아 본다.
export function AnswerFeedback({ message }: { message: ChatMessage }) {
  const feedback = useMessageFeedback()
  const [rating, setRating] = useState<FeedbackRating | null>(message.feedback ?? null)
  const [note, setNote] = useState(message.feedback_note ?? '')
  const [savedNote, setSavedNote] = useState(message.feedback_note ?? '')
  const [status, setStatus] = useState<string | null>(null)

  const rate = (next: FeedbackRating) => {
    const previous = { rating, note }
    const cleared = rating === next
    const nextNote = cleared ? '' : note.trim()
    setRating(cleared ? null : next)
    if (cleared) setNote('')
    setStatus(null)
    feedback.mutate(
      { messageId: message.id, rating: cleared ? null : next, note: nextNote || null },
      {
        onSuccess: () => {
          setSavedNote(nextNote)
          setStatus(cleared ? '평가를 지웠습니다.' : '평가를 저장했습니다.')
        },
        onError: () => {
          setRating(previous.rating)
          setNote(previous.note)
        },
      },
    )
  }

  const saveNote = () => {
    const trimmed = note.trim()
    if (feedback.isPending || trimmed === savedNote) return
    setStatus(null)
    feedback.mutate(
      { messageId: message.id, rating: 'down', note: trimmed || null },
      {
        onSuccess: () => {
          setSavedNote(trimmed)
          setStatus(trimmed ? '의견을 저장했습니다.' : '의견을 지웠습니다.')
        },
      },
    )
  }

  const handleNoteSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    saveNote()
  }

  const isNoteSaved = savedNote === note.trim()

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
        <form onSubmit={handleNoteSubmit} className="user-chat__feedback-note">
          <Input
            type="text"
            aria-label="무엇이 틀렸는지"
            placeholder="무엇이 틀렸나요? (선택, 칸에서 벗어나면 저장됩니다)"
            value={note}
            maxLength={NOTE_MAX_LENGTH}
            onChange={(e) => {
              setNote(e.target.value)
              setStatus(null)
            }}
            onBlur={saveNote}
            controlSize="sm"
          />
          <Button type="submit" size="sm" variant="secondary" disabled={feedback.isPending || isNoteSaved}>
            {isNoteSaved && note ? '저장됨' : '남기기'}
          </Button>
        </form>
      )}
      {status && (
        <span role="status" className="user-chat__feedback-status">
          {status}
        </span>
      )}
      {feedback.isError && <Alert tone="danger">{apiErrorDetail(feedback.error, '평가를 저장하지 못했습니다.')}</Alert>}
    </div>
  )
}
