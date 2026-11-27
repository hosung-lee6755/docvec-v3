import { Field, Select } from '../ui'
import { DOCUMENT_TYPE_HINT, DOCUMENT_TYPE_OPTIONS } from '../../lib/documentTypes'

interface DocumentTypeFieldProps {
  value: string
  onChange: (value: string) => void
  // 빈 값(지정 안 함)의 이름. 업로드에서는 컬렉션 기본값을, 컬렉션 화면에서는 자동 판별을 뜻한다
  autoLabel?: string
  hint?: string
}

// 문서 유형 선택(2026-11-27). 업로드, 컬렉션 생성·수정이 같은 선택지를 쓴다
export function DocumentTypeField({ value, onChange, autoLabel = '자동 판별', hint = DOCUMENT_TYPE_HINT }: DocumentTypeFieldProps) {
  return (
    <Field label="문서 유형" hint={hint}>
      {(id) => (
        <Select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
          <option value="">{autoLabel}</option>
          {DOCUMENT_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </Select>
      )}
    </Field>
  )
}
