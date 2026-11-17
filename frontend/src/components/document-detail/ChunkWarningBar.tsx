import { AlertTriangle } from 'lucide-react'
import { Button } from '../ui'

interface ChunkWarningBarProps {
  shortCount: number
  longCount: number
  // 지금 가리키는 대상의 순서(0부터). 아직 고르지 않았으면 -1
  currentIndex: number
  onlyFlagged: boolean
  onJump: (index: number) => void
  onOnlyFlaggedChange: (value: boolean) => void
}

/** 청크 탭 위에 붙어, 품질 경고 대상 청크가 몇 개인지 알려 주고 하나씩 찾아가게 한다. */
export default function ChunkWarningBar({
  shortCount, longCount, currentIndex, onlyFlagged, onJump, onOnlyFlaggedChange,
}: ChunkWarningBarProps) {
  const total = shortCount + longCount
  if (!total) return null
  const parts = [
    shortCount ? `너무 짧은 청크 ${shortCount}개` : '',
    longCount ? `너무 긴 청크 ${longCount}개` : '',
  ].filter(Boolean)
  return (
    <div className="ds-chunk-warning-bar" role="region" aria-label="품질 경고 대상 청크">
      <AlertTriangle size={14} style={{ flexShrink: 0 }} />
      <span className="ds-chunk-warning-bar__text">
        품질 경고 대상: {parts.join(', ')}
        {currentIndex >= 0 && ` · ${currentIndex + 1}/${total}번째를 보고 있습니다`}
      </span>
      <Button size="sm" variant="ghost" onClick={() => onJump((currentIndex - 1 + total) % total)} disabled={currentIndex < 0 || total < 2}>
        이전
      </Button>
      <Button size="sm" variant="primary" onClick={() => onJump((currentIndex + 1) % total)}>
        {currentIndex < 0 ? '첫 대상으로 이동' : '다음'}
      </Button>
      <label className="ds-chunk-warning-bar__toggle">
        <input type="checkbox" checked={onlyFlagged} onChange={(event) => onOnlyFlaggedChange(event.target.checked)} />
        대상만 보기
      </label>
    </div>
  )
}
