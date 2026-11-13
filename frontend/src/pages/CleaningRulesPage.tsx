import { useState } from 'react'
import { Loader2, Pencil, Plus, Trash2 } from 'lucide-react'
import {
  useCleaningRules, useCreateCleaningRule, useUpdateCleaningRule, useDeleteCleaningRule,
  type CleaningRule, type CleaningRuleInput, type CleaningRuleType, type CleaningRuleScope,
} from '../hooks/useCleaningRules'
import { Badge, Button, EmptyState, ErrorAlert, Field, IconButton, Input, Modal, Page, PageHeader, Select } from '../components/ui'
import '../styles/screens/pipeline.css'

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

function patternLabel(ruleType: CleaningRuleType): string {
  if (ruleType === 'REGEX_REPLACE') return '정규식 패턴'
  if (ruleType === 'LINE_FILTER') return '라인 매치 정규식'
  return '제거할 문자열'
}

function patternPlaceholder(ruleType: CleaningRuleType): string {
  if (ruleType === 'REGEX_REPLACE') return '예: \\s{2,}'
  if (ruleType === 'LINE_FILTER') return '예: ^페이지\\s*\\d+$'
  return '예: (주)데이터구루 내부용'
}

function RuleFormModal({
  initial, onCancel, onSave, isSaving, saveError,
}: {
  initial: CleaningRuleInput
  onCancel: () => void
  onSave: (input: CleaningRuleInput) => void
  isSaving: boolean
  /** 저장이 실패했을 때의 오류. 없으면 null */
  saveError: unknown
}) {
  const [form, setForm] = useState<CleaningRuleInput>(initial)

  return (
    <Modal
      isOpen
      title="정제 규칙"
      onClose={onCancel}
      footer={(
        <>
          <Button variant="secondary" onClick={onCancel}>취소</Button>
          <Button
            variant="primary"
            onClick={() => onSave(form)}
            disabled={isSaving || !form.rule_name.trim() || !form.pattern.trim()}
          >
            저장
          </Button>
        </>
      )}
    >
      <div className="pipeline-modal-stack">
        <Field label="이름">
          {(id) => (
            <Input
              id={id}
              value={form.rule_name}
              onChange={(e) => setForm({ ...form, rule_name: e.target.value })}
              placeholder="예: 반복 머리말 제거"
            />
          )}
        </Field>

        <Field label="유형">
          {(id) => (
            <Select
              id={id}
              value={form.rule_type}
              onChange={(e) => setForm({ ...form, rule_type: e.target.value as CleaningRuleType })}
            >
              {(Object.keys(RULE_TYPE_LABELS) as CleaningRuleType[]).map((t) => (
                <option key={t} value={t}>{RULE_TYPE_LABELS[t]}</option>
              ))}
            </Select>
          )}
        </Field>

        <Field label={patternLabel(form.rule_type)}>
          {(id) => (
            <Input
              id={id}
              value={form.pattern}
              onChange={(e) => setForm({ ...form, pattern: e.target.value })}
              style={{ fontFamily: 'var(--font-mono)' }}
              placeholder={patternPlaceholder(form.rule_type)}
            />
          )}
        </Field>

        {form.rule_type === 'REGEX_REPLACE' && (
          <Field label="치환 결과 (비우면 제거)">
            {(id) => (
              <Input
                id={id}
                value={form.replacement ?? ''}
                onChange={(e) => setForm({ ...form, replacement: e.target.value })}
                style={{ fontFamily: 'var(--font-mono)' }}
                placeholder="예: 공백 1칸 (비우면 매치된 부분을 완전히 제거)"
              />
            )}
          </Field>
        )}

        <div style={{ display: 'flex', gap: 'var(--space-3)' }}>
          <Field label="적용 범위" className="pipeline-field-grow">
            {(id) => (
              <Select
                id={id}
                value={form.scope}
                onChange={(e) => setForm({ ...form, scope: e.target.value as CleaningRuleScope })}
              >
                {(Object.keys(SCOPE_LABELS) as CleaningRuleScope[]).map((s) => (
                  <option key={s} value={s}>{SCOPE_LABELS[s]}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="우선순위" className="pipeline-field-narrow">
            {(id) => (
              <Input
                id={id}
                type="number"
                value={form.priority}
                onChange={(e) => setForm({ ...form, priority: Number(e.target.value) })}
              />
            )}
          </Field>
        </div>

        <label className="block-panel__check">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => setForm({ ...form, enabled: e.target.checked })}
          />
          활성화
        </label>
        {saveError != null && <ErrorAlert error={saveError} message="정제 규칙을 저장하지 못했습니다." />}
      </div>
    </Modal>
  )
}

export default function CleaningRulesPage() {
  const { data, isLoading, isError, error, refetch } = useCleaningRules()
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
    <Page>
      <PageHeader
        title="정제 규칙"
        subtitle="텍스트 정제 블록이 문서 처리 시 적용하는 사용자 정의 규칙입니다."
        actions={(<>
          {data && <span className="ds-toolbar__meta">{`${rules.length}건`}</span>}
          <Button variant="primary" icon={<Plus size={14} aria-hidden="true" />} onClick={() => setEditing('new')}>
            새 규칙
          </Button>
        </>)}
      />


      <div style={{ padding: 'var(--space-4) var(--space-5)', display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 'var(--space-8)' }}>
            <Loader2 size={20} className="pipeline-spin" style={{ color: 'var(--color-text-muted)' }} aria-label="불러오는 중" />
          </div>
        )}

        {isError && <ErrorAlert error={error} message="정제 규칙 목록을 불러오지 못했습니다." onRetry={() => refetch()} />}
        {del.isError && <ErrorAlert error={del.error} message="정제 규칙을 삭제하지 못했습니다." />}

        {!isLoading && !isError && !rules.length && (
          <EmptyState title="등록된 정제 규칙이 없습니다." description="새 규칙을 만들면 텍스트 정제 블록이 문서 처리 때 적용합니다." />
        )}

        {!!rules.length && (
          <div className="ds-table-wrap">
            <table className="ds-table">
              <thead>
                <tr>
                  <th>이름</th>
                  <th>유형</th>
                  <th>패턴</th>
                  <th>치환</th>
                  <th>범위</th>
                  <th className="ds-cell-num">우선순위</th>
                  <th>활성화</th>
                  <th aria-label="작업" />
                </tr>
              </thead>
              <tbody>
                {rules.map((rule) => (
                  <tr key={rule.id} className={rule.enabled ? undefined : 'is-warning'}>
                    <td>{rule.rule_name}</td>
                    <td>{RULE_TYPE_LABELS[rule.rule_type as CleaningRuleType] ?? rule.rule_type}</td>
                    <td style={{
                      fontFamily: 'var(--font-mono)', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {rule.pattern ?? '-'}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)' }}>{rule.replacement || '(제거)'}</td>
                    <td>{SCOPE_LABELS[rule.scope]}</td>
                    <td className="ds-cell-num">{rule.priority}</td>
                    <td>
                      <Badge tone={rule.enabled ? 'success' : 'neutral'} hasDot>
                        {rule.enabled ? '사용' : '중지'}
                      </Badge>
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {confirmDeleteId === rule.id ? (
                        <div className="pipeline-confirm">
                          <span className="pipeline-confirm__text">삭제하시겠습니까?</span>
                          <Button
                            variant="danger-solid"
                            size="sm"
                            onClick={() => del.mutate(rule.id, { onSuccess: () => setConfirmDeleteId(null) })}
                            disabled={del.isPending}
                          >
                            확인
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => setConfirmDeleteId(null)}>취소</Button>
                        </div>
                      ) : (
                        <div style={{ display: 'inline-flex', gap: 'var(--space-1)' }}>
                          <IconButton label="규칙 수정" onClick={() => setEditing(rule)}>
                            <Pencil size={13} aria-hidden="true" />
                          </IconButton>
                          <IconButton label="규칙 삭제" tone="danger" onClick={() => setConfirmDeleteId(rule.id)}>
                            <Trash2 size={13} aria-hidden="true" />
                          </IconButton>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

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
          onCancel={() => { create.reset(); update.reset(); setEditing(null) }}
          onSave={handleSave}
          isSaving={create.isPending || update.isPending}
          saveError={create.isError ? create.error : update.isError ? update.error : null}
        />
      )}
    </Page>
  )
}
