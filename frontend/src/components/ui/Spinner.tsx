interface SpinnerProps {
  size?: number
}

export function Spinner({ size = 20 }: SpinnerProps) {
  return (
    <>
      <style>{`
        @keyframes spinner-spin {
          from { transform: rotate(0deg); }
          to { transform: rotate(360deg); }
        }
      `}</style>
      <span
        style={{
          display: 'inline-block',
          width: size,
          height: size,
          border: `2px solid var(--color-border)`,
          borderTopColor: 'var(--color-accent)',
          borderRadius: '50%',
          animation: 'spinner-spin 0.7s linear infinite',
          flexShrink: 0,
        }}
        aria-label="로딩 중"
        role="status"
      />
    </>
  )
}
