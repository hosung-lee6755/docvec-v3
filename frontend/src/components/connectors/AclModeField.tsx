import type { AclMode } from '../../hooks/useConnectors'
import { ACL_MODE_LABELS } from './connectorLabels'
import { Alert } from '../ui'

// 원천 연결의 권한 기준. 값의 정본은 백엔드 source_connector.ACL_MODE_*다.

const ACL_MODE_HINTS: Record<AclMode, string> = {
  file_acl: '파일마다 걸린 NTFS 권한을 그대로 옮깁니다. 권한을 사람과 그룹에 연결하려면 사내 AD 연결이 필요합니다.',
  collection_only: '파일 권한을 읽지 않고 모두 가져옵니다. 이 컬렉션을 볼 수 있는 사람은 가져온 문서를 모두 봅니다.',
}

interface AclModeFieldProps {
  value: AclMode
  onChange: (mode: AclMode) => void
  /** 사내 AD 로그인을 쓰는가. 쓰지 않으면 파일 서버 권한을 사람과 연결할 수 없다. */
  hasDirectory: boolean
  disabled?: boolean
}

/** 권한 기준 선택과, 고른 방식이 무엇을 뜻하는지에 대한 경고 */
export default function AclModeField({ value, onChange, hasDirectory, disabled }: AclModeFieldProps) {
  return (
    <fieldset className="connector-acl-mode" disabled={disabled}>
      <legend className="ds-field__label">권한 기준</legend>
      {(Object.keys(ACL_MODE_LABELS) as AclMode[]).map((mode) => (
        <label key={mode} className="connector-acl-mode__option">
          <input
            type="radio"
            name="acl_mode"
            value={mode}
            checked={value === mode}
            onChange={() => onChange(mode)}
          />
          <span>
            <strong>{ACL_MODE_LABELS[mode]}</strong>
            <span className="ds-cell-sub">{ACL_MODE_HINTS[mode]}</span>
          </span>
        </label>
      ))}
      {value === 'collection_only' && (
        <Alert tone="warning">
          파일 서버에서 일부 사람만 보도록 막아 둔 문서도 이 컬렉션 구성원 모두에게 열립니다.
          민감한 폴더는 따로 연결해 접근이 좁은 컬렉션에 넣거나, 경로별 보안등급 규칙으로 등급을 올리세요.
        </Alert>
      )}
      {value === 'file_acl' && !hasDirectory && (
        <Alert tone="warning">
          사내 AD 연결이 꺼져 있어 파일 권한을 사람과 그룹에 연결할 수 없습니다.
          모두에게 열린 파일만 가져오고 나머지는 보류됩니다.
        </Alert>
      )}
    </fieldset>
  )
}
