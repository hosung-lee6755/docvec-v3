import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ChatMessage } from '../../hooks/useChat'
import { AnswerFeedback } from './AnswerFeedback'

type MutateOptions = { onSuccess?: () => void; onError?: () => void }
const mutate = vi.fn()
let isPending = false

vi.mock('../../hooks/useChat', () => ({
  useMessageFeedback: () => ({ mutate, isPending, isError: false, error: null }),
}))

const message = (overrides: Partial<ChatMessage> = {}) =>
  ({ id: 'm1', feedback: null, feedback_note: null, ...overrides }) as ChatMessage

const succeed = () => mutate.mockImplementation((_input: unknown, options?: MutateOptions) => options?.onSuccess?.())
const fail = () => mutate.mockImplementation((_input: unknown, options?: MutateOptions) => options?.onError?.())

describe('AnswerFeedback', () => {
  beforeEach(() => {
    mutate.mockReset()
    isPending = false
  })

  it('누르는 즉시 눌린 상태로 바뀌고 저장되면 알린다', () => {
    succeed()
    render(<AnswerFeedback message={message()} />)
    fireEvent.click(screen.getByRole('button', { name: '도움이 됨' }))
    expect(screen.getByRole('button', { name: '도움이 됨' })).toHaveAttribute('aria-pressed', 'true')
    expect(mutate).toHaveBeenCalledWith({ messageId: 'm1', rating: 'up', note: null }, expect.anything())
    expect(screen.getByRole('status')).toHaveTextContent('평가를 저장했습니다.')
  })

  it('저장에 실패하면 눌린 상태를 되돌린다', () => {
    fail()
    render(<AnswerFeedback message={message()} />)
    fireEvent.click(screen.getByRole('button', { name: '도움이 안 됨' }))
    expect(screen.getByRole('button', { name: '도움이 안 됨' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('같은 버튼을 다시 누르면 평가를 지운다', () => {
    succeed()
    render(<AnswerFeedback message={message({ feedback: 'up' })} />)
    fireEvent.click(screen.getByRole('button', { name: '도움이 됨' }))
    expect(screen.getByRole('button', { name: '도움이 됨' })).toHaveAttribute('aria-pressed', 'false')
    expect(mutate).toHaveBeenCalledWith({ messageId: 'm1', rating: null, note: null }, expect.anything())
    expect(screen.getByRole('status')).toHaveTextContent('평가를 지웠습니다.')
  })

  it('의견 칸에서 벗어나면 바뀐 의견을 저장한다', () => {
    succeed()
    render(<AnswerFeedback message={message({ feedback: 'down' })} />)
    const input = screen.getByRole('textbox', { name: '무엇이 틀렸는지' })
    fireEvent.change(input, { target: { value: '날짜가 틀렸어요' } })
    fireEvent.blur(input)
    expect(mutate).toHaveBeenCalledWith({ messageId: 'm1', rating: 'down', note: '날짜가 틀렸어요' }, expect.anything())
    expect(screen.getByRole('status')).toHaveTextContent('의견을 저장했습니다.')
    expect(screen.getByRole('button', { name: '저장됨' })).toBeDisabled()
  })

  it('의견이 그대로면 벗어나도 다시 저장하지 않는다', () => {
    succeed()
    render(<AnswerFeedback message={message({ feedback: 'down', feedback_note: '출처가 없어요' })} />)
    fireEvent.blur(screen.getByRole('textbox', { name: '무엇이 틀렸는지' }))
    expect(mutate).not.toHaveBeenCalled()
  })

  it('저장 중에는 평가 버튼을 다시 누를 수 없다', () => {
    isPending = true
    render(<AnswerFeedback message={message()} />)
    expect(screen.getByRole('button', { name: '도움이 됨' })).toBeDisabled()
  })
})
