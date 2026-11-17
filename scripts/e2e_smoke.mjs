#!/usr/bin/env node
// 핵심 흐름 E2E 점검(전체 점검 2-9, 2026-11-16).
//
// 떠 있는 스택에 대고 "올리기 → 처리 → 검색 → 답변"을 실제로 한 번 돈다. 단위 테스트는 GPU 워커,
// Qdrant, 추론 서버를 흉내 내므로 이 흐름이 통째로 도는지는 여기서만 확인된다. 배포 전에 돌린다.
//
//   E2E_BASE_URL=https://192.168.0.3:13443 E2E_EMAIL=... E2E_PASSWORD=... node scripts/e2e_smoke.mjs
//
// 환경 변수
//   E2E_BASE_URL   서비스 주소(끝에 /api/v1 없이)
//   E2E_EMAIL, E2E_PASSWORD   로그인할 계정. 대신 E2E_TOKEN에 접근 토큰을 넣어도 된다
//   E2E_MODEL      답변 모델 키(기본 qwen2.5-3b)
//   E2E_INSECURE=1 자체 서명 인증서를 받아들인다(개발 환경)
//   E2E_KEEP=1     끝난 뒤 임시 컬렉션을 지우지 않는다(실패 원인을 화면에서 볼 때)
//
// 임시 컬렉션 하나와 문서 한 건을 만들고, 끝나면 지운다. 실패하면 0이 아닌 코드로 끝난다.

const BASE = `${(process.env.E2E_BASE_URL || 'https://localhost:13443').replace(/\/$/, '')}/api/v1`
const MODEL = process.env.E2E_MODEL || 'qwen2.5-3b'
const PROCESS_TIMEOUT_MS = 10 * 60 * 1000
const ANSWER_TIMEOUT_MS = 5 * 60 * 1000
const POLL_MS = 5000
// 다른 문서에 없을 낱말. 검색이 이 문서를 찾았는지와 답변이 이 값을 말했는지를 이것으로 가린다
const MARKER = `E2E-${Date.now().toString(36).toUpperCase()}`
const FACT = '37'
const DOCUMENT_TEXT = [
  `# ${MARKER} 점검 문서`,
  '',
  '## 1. 개요',
  `이 문서는 핵심 흐름 점검용입니다. ${MARKER} 사업의 참여 기관은 모두 ${FACT}곳입니다.`,
  '참여 기관은 매 분기 실적 보고서를 제출해야 하며, 제출 기한은 분기 종료 후 15일 이내입니다.',
  '',
  '## 2. 지원 조건',
  '지원 기간은 최대 1년이고, 지원 비율은 총사업비의 50% 이내입니다.',
  '중간 평가에서 기준에 미달하면 다음 분기 지원금이 보류됩니다.',
].join('\n')

if (process.env.E2E_INSECURE === '1') process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0'

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
let token = process.env.E2E_TOKEN || ''
const steps = []

async function api(method, path, body, { raw = false } = {}) {
  const headers = { Authorization: `Bearer ${token}` }
  const isForm = body instanceof FormData
  if (body && !isForm) headers['Content-Type'] = 'application/json'
  const response = await fetch(`${BASE}${path}`, {
    method, headers, body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })
  if (raw) return response
  const text = await response.text()
  if (!response.ok) throw new Error(`${method} ${path} → ${response.status} ${text.slice(0, 200)}`)
  return text ? JSON.parse(text) : null
}

async function step(name, run) {
  const started = Date.now()
  try {
    const note = await run()
    steps.push({ name, ok: true, seconds: Math.round((Date.now() - started) / 1000), note })
    console.log(`  통과  ${name}${note ? `  (${note})` : ''}`)
  } catch (error) {
    steps.push({ name, ok: false, note: error.message })
    console.log(`  실패  ${name}\n        ${error.message}`)
    throw error
  }
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function waitForIndexed(documentId) {
  const deadline = Date.now() + PROCESS_TIMEOUT_MS
  const resumed = new Set()
  for (;;) {
    const doc = await api('GET', `/documents/${documentId}`)
    if (doc.status === 'INDEXED') return doc
    if (doc.status === 'FAILED') throw new Error(`문서 처리가 실패했습니다: ${doc.error_message}`)
    // 품질 기준에 걸려 검토 대기로 멈추면 승인하고 이어 간다(사람이 화면에서 하는 일과 같다)
    if (doc.status === 'WAITING_REVIEW' && doc.active_run_id && !resumed.has(doc.active_run_id)) {
      resumed.add(doc.active_run_id)
      await api('POST', `/workflows/runs/${doc.active_run_id}/resume`, {})
    }
    if (Date.now() > deadline) throw new Error(`제한 시간 안에 처리가 끝나지 않았습니다(마지막 상태 ${doc.status})`)
    await sleep(POLL_MS)
  }
}

async function readStream(messageId) {
  const response = await api('GET', `/chat/${messageId}/stream`, null, { raw: true })
  assert(response.ok, `스트림이 열리지 않았습니다(${response.status})`)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  const counts = {}
  let buffer = ''
  const deadline = Date.now() + ANSWER_TIMEOUT_MS
  for (;;) {
    const { done, value } = await reader.read()
    if (done) return counts
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop()
    for (const block of blocks) {
      const name = /^event: (\w+)/m.exec(block)?.[1]
      if (name) counts[name] = (counts[name] || 0) + 1
    }
    if (counts.done || counts.timeout) return counts
    if (Date.now() > deadline) throw new Error('답변 스트림이 제한 시간 안에 끝나지 않았습니다')
  }
}

async function main() {
  console.log(`대상: ${BASE}`)
  let collectionId = null
  let documentId = null
  let conversationId = null
  try {
    await step('로그인', async () => {
      if (token) return '토큰 사용'
      assert(process.env.E2E_EMAIL && process.env.E2E_PASSWORD, 'E2E_EMAIL과 E2E_PASSWORD, 또는 E2E_TOKEN이 필요합니다')
      const result = await api('POST', '/auth/login', { email: process.env.E2E_EMAIL, password: process.env.E2E_PASSWORD })
      token = result.access_token
      assert(token, '로그인 응답에 access_token이 없습니다')
    })

    await step('임시 컬렉션 만들기', async () => {
      const collection = await api('POST', '/collections', { name: `E2E 점검 ${MARKER}`, description: '자동 점검용. 지워도 됩니다.' })
      collectionId = collection.id
    })

    await step('문서 올리기', async () => {
      const form = new FormData()
      form.append('file', new Blob([DOCUMENT_TEXT], { type: 'text/markdown' }), `${MARKER}.md`)
      form.append('collection_id', collectionId)
      const uploaded = await api('POST', '/documents/upload', form)
      documentId = uploaded.id
      assert(documentId, '올린 문서의 id가 없습니다')
    })

    await step('처리가 끝나 검색 가능 상태가 되기', async () => {
      const doc = await waitForIndexed(documentId)
      return `청크 ${doc.chunk_count ?? '?'}개`
    })

    await step('검색이 올린 문서를 찾기', async () => {
      const result = await api('POST', '/search', { query: `${MARKER} 참여 기관`, collection_id: collectionId, limit: 5 })
      assert(result.items.length > 0, '검색 결과가 없습니다')
      assert(result.items[0].document_id === documentId, '첫 결과가 올린 문서가 아닙니다')
      assert(result.items.some((item) => item.content.includes(MARKER)), '결과 본문에 점검용 낱말이 없습니다')
      return `${result.items.length}건`
    })

    let messageId = null
    await step('질문 보내기', async () => {
      const conversation = await api('POST', '/chat/conversations', {
        query: `${MARKER} 사업의 참여 기관은 모두 몇 곳입니까?`, collection_id: collectionId, model_key: MODEL,
      })
      conversationId = conversation.id
      messageId = conversation.messages.at(-1).id
    })

    await step('답변이 스트림으로 오기', async () => {
      const counts = await readStream(messageId)
      assert(counts.done, '스트림이 done 없이 끝났습니다')
      return `partial ${counts.partial || 0}회`
    })

    await step('답변에 근거와 정답이 있기', async () => {
      const message = await api('GET', `/chat/${messageId}`)
      assert(message.status === 'DONE', `답변 상태가 ${message.status}입니다: ${message.error_message || ''}`)
      assert((message.answer || '').includes(FACT), `답변에 정답(${FACT})이 없습니다: ${(message.answer || '').slice(0, 120)}`)
      assert((message.citations || []).length > 0, '답변에 인용이 없습니다')
      assert(message.citations.some((citation) => citation.document_id === documentId), '인용이 올린 문서를 가리키지 않습니다')
      assert(message.ai_generated === true, 'AI 생성 표시가 없습니다')
      return `인용 ${message.citations.length}건`
    })

    await step('알림 목록 읽기', async () => {
      const list = await api('GET', '/notifications?limit=5')
      assert(Array.isArray(list.items) && typeof list.unread_count === 'number', '알림 응답 모양이 다릅니다')
      return `읽지 않은 알림 ${list.unread_count}건`
    })
  } finally {
    if (process.env.E2E_KEEP === '1') {
      console.log(`  임시 컬렉션을 남겨 둡니다: ${collectionId}`)
    } else if (token) {
      // 정리 실패는 점검 결과를 바꾸지 않는다. 남은 것만 알려 준다
      if (conversationId) await api('DELETE', `/chat/conversations/${conversationId}`).catch(() => null)
      if (collectionId) {
        await api('DELETE', `/collections/${collectionId}`)
          .catch((error) => console.log(`  임시 컬렉션을 지우지 못했습니다(${collectionId}): ${error.message}`))
      }
    }
  }
}

main()
  .then(() => {
    console.log(`\n모두 통과했습니다(${steps.length}단계).`)
  })
  .catch(() => {
    console.log(`\n실패했습니다. 통과 ${steps.filter((item) => item.ok).length}단계, 실패 1단계.`)
    process.exitCode = 1
  })
