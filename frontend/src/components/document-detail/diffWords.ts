export type DiffOp = { type: 'equal' | 'remove' | 'add'; text: string }

// 공백을 보존하며 토큰화한 뒤 LCS 기반으로 정렬한다 — 짧은 샘플(최대 200자)에만
// 쓰이므로 O(n*m)이어도 성능에 문제가 없고, 문자 단위 diff보다 단어 단위가
// 한글/영문 혼합 문장에서 훨씬 읽기 쉽다.
function _tokenize(text: string): string[] {
  return text.split(/(\s+)/).filter((t) => t.length > 0)
}

export function diffWords(before: string, after: string): DiffOp[] {
  const a = _tokenize(before)
  const b = _tokenize(after)
  const n = a.length
  const m = b.length
  const lcs: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }
  const ops: DiffOp[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      ops.push({ type: 'equal', text: a[i] })
      i += 1
      j += 1
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      ops.push({ type: 'remove', text: a[i] })
      i += 1
    } else {
      ops.push({ type: 'add', text: b[j] })
      j += 1
    }
  }
  while (i < n) {
    ops.push({ type: 'remove', text: a[i] })
    i += 1
  }
  while (j < m) {
    ops.push({ type: 'add', text: b[j] })
    j += 1
  }
  const merged: DiffOp[] = []
  for (const op of ops) {
    const last = merged[merged.length - 1]
    if (last && last.type === op.type) last.text += op.text
    else merged.push({ ...op })
  }
  return merged
}
