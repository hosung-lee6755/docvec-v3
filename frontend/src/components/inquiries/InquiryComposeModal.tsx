import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, ErrorAlert, Field, Input, Modal, Select, Textarea } from '../ui'
import { INQUIRY_CATEGORY_LABELS } from '../../lib/inquiryLabels'
import {
  useCreateInquiry,
  type InquiryCategory,
} from '../../hooks/useInquiries'

// 문의 작성 대화상자. 실패 화면에서 넘어오면 문서와 분류가 미리 채워진다.

export interface InquiryPrefill {
  documentId?: string
  documentName?: string
  category?: InquiryCategory
}

interface InquiryComposeModalProps {
  isOpen: boolean
  prefill: InquiryPrefill
  onClose: () => void
  onCreated: (inquiryId: string) => void
}

const CATEGORIES = Object.keys(INQUIRY_CATEGORY_LABELS) as InquiryCategory[]

export function InquiryComposeModal({ isOpen, prefill, onClose, onCreated }: InquiryComposeModalProps) {
  const create = useCreateInquiry()
  const [category, setCategory] = useState<InquiryCategory>(prefill.category ?? 'question')
  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const documentId = prefill.documentId
  const canSend = title.trim() !== '' && body.trim() !== '' && !create.isPending

  const handleSend = () => {
    if (!canSend) return
    create.mutate(
      {
        title: title.trim(),
        body: body.trim(),
        category,
        ...(documentId ? { document_id: documentId } : {}),
      },
      { onSuccess: (detail) => onCreated(detail.id) },
    )
  }

  return (
    <Modal
      isOpen={isOpen}
      title="관리자에게 문의하기"
      onClose={onClose}
      size="lg"
      isDismissible={!create.isPending}
      footer={(
        <>
          <Button variant="secondary" onClick={onClose} disabled={create.isPending}>취소</Button>
          <Button variant="primary" onClick={handleSend} disabled={!canSend}>보내기</Button>
        </>
      )}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
        {documentId && (
          <p className="ds-cell-sub" style={{ margin: 0 }}>
            연결된 문서: <Link to={`/documents/${documentId}`}>{prefill.documentName ?? '문서 보기'}</Link>
            {' '}문서의 오류 기록이 문의와 함께 저장됩니다.
          </p>
        )}
        <Field label="분류">
          {(id) => (
            <Select id={id} value={category} onChange={(e) => setCategory(e.target.value as InquiryCategory)}>
              {CATEGORIES.map((value) => (
                <option key={value} value={value}>{INQUIRY_CATEGORY_LABELS[value]}</option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="제목" hint="200자 이내로 입력하세요.">
          {(id) => (
            <Input id={id} value={title} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
          )}
        </Field>
        <Field label="내용" hint="어떤 작업을 했고 무엇이 어떻게 잘못되었는지 적어 주시면 답하기 쉽습니다. 5000자 이내.">
          {(id) => (
            <Textarea id={id} rows={8} value={body} maxLength={5000} onChange={(e) => setBody(e.target.value)} />
          )}
        </Field>
        {create.isError && <ErrorAlert error={create.error} message="문의를 보내지 못했습니다." />}
      </div>
    </Modal>
  )
}
