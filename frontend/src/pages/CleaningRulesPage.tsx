import { useState } from 'react'
import { Loader2, Pencil, Trash2, X } from 'lucide-react'
import {
  useCleaningRules, useCreateCleaningRule, useUpdateCleaningRule, useDeleteCleaningRule,
  type CleaningRule, type CleaningRuleInput, type CleaningRuleType, type CleaningRuleScope,
} from '../hooks/useCleaningRules'

const RULE_TYPE_LABELS: Record<CleaningRuleType, string> = {
  REGEX_REPLACE: '정규식 치환', EXACT_REMOVE: '문자열 제거', LINE_FILTER: '라인 필터',
}
const SCOPE_LABELS: Record<CleaningRuleScope, string> = {
  DOCUMENT: '문서 전체', PARAGRAPH: '문단', LINE: '라인',
}

const EMPTY_FORM: CleaningRuleInput = {
  rule_name: '', rule_type: 'REGEX_REPLACE', pattern: '', replacement: '',
  scope: 'PARAGRAPH', priority: 0, enabled: true,
}

function RuleFormModal({
  initial, onCancel, onSave, isSaving,
}: {
  initial: CleaningRuleInput
  onCancel: () => void
  onSave: (input: CleaningRuleInput) => void
  isSaving: boolean
}) {
  const [form, setForm] = useState<CleaningRuleInput>(initial)

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
    }}>
      <section className="krds-modal fade shown in" role="dialog">
        <div className="modal-dialog modal-md">
          <div className="modal-content">
            <div className="modal-header">
              <h2 className="modal-title">정제 규칙</h2>
            </div>
            <div className="modal-conts">
              <div className="conts-area" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-4)' }}>
                <div className="form-group">
                  <div className="form-tit"><label htmlFor="cleaning_rule_name">이름</label></div>
                  <div className="form-conts">
                    <input
                      id="cleaning_rule_name"
                      className="krds-input"
                      value={form.rule_name}
                      onChange={(e) => setForm({ ...form, rule_name: e.target.value })}
                      placeholder="예: 반복 머리말 제거"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <div className="form-tit"><label htmlFor="cleaning_rule_type">유형</label></div>
                  <div className="form-conts">
                    <select
                      id="cleaning_rule_type"
                      className="krds-form-select"
                      value={form.rule_type}
                      onChange={(e) => setForm({ ...form, rule_type: e.target.value as CleaningRuleType })}
                    >
                      {(Object.keys(RULE_TYPE_LABELS) as CleaningRuleType[]).map((t) => (
                        <option key={t} value={t}>{RULE_TYPE_LABELS[t]}</option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="form-group">
                  <div className="form-tit">
                    <label htmlFor="cleaning_rule_pattern">
                      {form.rule_type === 'REGEX_REPLACE' ? '정규식 패턴' : form.rule_type === 'LINE_FILTER' ? '라인 매치 정규식' : '제거할 문자열'}
                    </label>
                  </div>
                  <div className="form-conts">
                    <input
                      id="cleaning_rule_pattern"
                      className="krds-input"
                      value={form.pattern}
                      onChange={(e) => setForm({ ...form, pattern: e.target.value })}
                      style={{ fontFamily: 'monospace' }}
                      placeholder={
                        form.rule_type === 'REGEX_REPLACE' ? '예: \\s{2,}'
                          : form.rule_type === 'LINE_FILTER' ? '예: ^페이지\\s*\\d+$'
                          : '예: (주)데이터구루 내부용'
                      }
                    />
                  </div>
                </div>

                {form.rule_type === 'REGEX_REPLACE' && (
                  <div className="form-group">
                    <div className="form-tit"><label htmlFor="cleaning_rule_replacement">치환 결과 (비우면 제거)</label></div>
                    <div className="form-conts">
                      <input
                        id="cleaning_rule_replacement"
                        className="krds-input"
                        value={form.replacement ?? ''}
                        onChange={(e) => setForm({ ...form, replacement: e.target.value })}
                        style={{ fontFamily: 'monospace' }}
                        placeholder="예: 공백 1칸 (비우면 매치된 부분을 완전히 제거)"
                      />
                    </div>
                  </div>
                )}

                <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
                  <div className="form-group" style={{ flex: 1 }}>
                    <div className="form-tit"><label htmlFor="cleaning_rule_scope">적용 범위</label></div>
                    <div className="form-conts">
                      <select
                        id="cleaning_rule_scope"
                        className="krds-form-select"
                        value={form.scope}
                        onChange={(e) => setForm({ ...form, scope: e.target.value as CleaningRuleScope })}
                      >
                        {(Object.keys(SCOPE_LABELS) as CleaningRuleScope[]).map((s) => (
                          <option key={s} value={s}>{SCOPE_LABELS[s]}</option>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="form-group" style={{ width: 100 }}>
                    <div className="form-tit"><label htmlFor="cleaning_rule_priority">우선순위</label></div>
                    <div className="form-conts">
                      <input
                        id="cleaning_rule_priority"
                        type="number"
                        className="krds-input"
                        value={form.priority}
                        onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
                      />
                    </div>
                  </div>
                </div>

                <div className="krds-form-check">
                  <input
                    type="checkbox"
                    id="cleaning_rule_enabled"
                    checked={form.enabled}
                    onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
                  />
                  <label htmlFor="cleaning_rule_enabled">활성화</label>
                </div>

                <div className="modal-btn btn-wrap">
                  <button type="button" onClick={onCancel} className="krds-btn medium secondary">취소</button>
                  <button
                    type="button"
                    onClick={() => onSave(form)}
                    disabled={isSaving || !form.rule_name.trim() || !form.pattern.trim()}
                    className="krds-btn medium primary"
                  >
                    저장
                  </button>
                </div>
              </div>
            </div>
            <button type="button" className="krds-btn medium icon btn-close close-modal" onClick={onCancel}>
              <span className="sr-only">닫기</span>
              <X size={20} />
            </button>
          </div>
        </div>
        <div className="modal-back"></div>
      </section>
    </div>
  )
}

export default function CleaningRulesPage() {
  const { data, isLoading } = useCleaningRules()
  const create = useCreateCleaningRule()
  const update = useUpdateCleaningRule()
  const del = useDeleteCleaningRule()
  const [editing, setEditing] = useState<CleaningRule | 'new' | null>(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const rules = data?.items ?? []

  const handleSave = (input: CleaningRuleInput) => {
    if (editing === 'new') {
      create.mutate(input, { onSuccess: () => setEditing(null) })
    } else if (editing) {
      update.mutate({ id: editing.id, ...input }, { onSuccess: () => setEditing(null) })
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 'var(--space-6)' }}>
        <div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: '0 0 4px' }}>정제 규칙</h1>
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
            텍스트 정제 블록이 문서 처리 시 적용하는 사용자 정의 규칙입니다.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setEditing('new')}
          className="krds-btn primary small"
          style={{ cursor: 'pointer' }}
        >
          + 새 규칙
        </button>
      </div>

      {isLoading && (
        <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
          <Loader2 size={20} style={{ animation: 'spin 1s linear infinite', color: 'var(--color-text-muted)' }} />
        </div>
      )}

      {!isLoading && !rules.length && (
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>등록된 정제 규칙이 없습니다.</p>
      )}

      {!!rules.length && (
        <div style={{ overflowX: 'auto', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-sm)' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
            <thead>
              <tr style={{ background: 'rgba(148,163,184,0.08)' }}>
                {['이름', '유형', '패턴', '치환', '범위', '우선순위', '활성화', '작업'].map((h) => (
                  <th key={h} style={{ textAlign: 'left', padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rules.map((rule) => (
                <tr key={rule.id}>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>{rule.rule_name}</td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>{RULE_TYPE_LABELS[rule.rule_type as CleaningRuleType] ?? rule.rule_type}</td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)', fontFamily: 'monospace', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {rule.pattern ?? '-'}
                  </td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)', fontFamily: 'monospace' }}>
                    {rule.replacement || '(제거)'}
                  </td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>{SCOPE_LABELS[rule.scope]}</td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>{rule.priority}</td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>
                    <span className={`krds-badge xsmall ${rule.enabled ? 'bg-success' : 'bg-gray'}`}>
                      {rule.enabled ? '사용' : '중지'}
                    </span>
                  </td>
                  <td style={{ padding: '8px 12px', borderBottom: '1px solid var(--color-border)' }}>
                    {confirmDeleteId === rule.id ? (
                      <div style={{ display: 'flex', gap: 'var(--space-2)', alignItems: 'center' }}>
                        <span style={{ fontSize: 12, color: '#dc2626' }}>삭제하시겠습니까?</span>
                        <button
                          type="button"
                          onClick={() => del.mutate(rule.id, { onSuccess: () => setConfirmDeleteId(null) })}
                          disabled={del.isPending}
                          className="krds-btn xsmall primary"
                        >
                          확인
                        </button>
                        <button type="button" onClick={() => setConfirmDeleteId(null)} className="krds-btn xsmall secondary">
                          취소
                        </button>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button type="button" onClick={() => setEditing(rule)} className="krds-btn text xsmall icon-btn">
                          <Pencil size={13} />
                        </button>
                        <button type="button" onClick={() => setConfirmDeleteId(rule.id)} className="krds-btn text xsmall icon-btn danger">
                          <Trash2 size={13} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <RuleFormModal
          initial={editing === 'new' ? EMPTY_FORM : {
            rule_name: editing.rule_name,
            rule_type: editing.rule_type as CleaningRuleType,
            pattern: editing.pattern ?? '',
            replacement: editing.replacement ?? '',
            scope: editing.scope,
            priority: editing.priority,
            enabled: editing.enabled,
          }}
          onCancel={() => setEditing(null)}
          onSave={handleSave}
          isSaving={create.isPending || update.isPending}
        />
      )}

    </div>
  )
}
