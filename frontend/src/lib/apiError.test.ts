import { describe, expect, it } from 'vitest'
import { AxiosError, AxiosHeaders } from 'axios'
import { apiErrorDetail, describeError, errorCause, explainFailure } from './apiError'

function httpError(status: number, detail?: unknown): AxiosError {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('Request failed', 'ERR_BAD_RESPONSE', config, {}, {
    status,
    statusText: '',
    headers: {},
    config,
    data: detail === undefined ? {} : { detail },
  })
}

describe('errorCause', () => {
  it('서버에 닿지 못하면 연결 문제라고 알린다', () => {
    const error = new AxiosError('Network Error', 'ERR_NETWORK')
    expect(errorCause(error)).toContain('서버에 연결할 수 없습니다')
  })

  it('시간 초과는 응답 지연이라고 알린다', () => {
    const error = new AxiosError('timeout', 'ECONNABORTED')
    expect(errorCause(error)).toContain('응답이 너무 늦습니다')
  })

  it('한국어 detail은 그대로 쓴다', () => {
    expect(errorCause(httpError(400, '기간은 최대 366일입니다.'))).toBe('기간은 최대 366일입니다.')
  })

  it('영어 not found detail은 대상 이름을 한국어로 바꾼다', () => {
    expect(errorCause(httpError(404, 'Document not found'))).toContain('문서를 찾을 수 없습니다')
  })

  it('영어 detail은 상태 코드에 맞는 한국어 원인으로 바꾼다', () => {
    expect(errorCause(httpError(403, 'Access denied'))).toContain('권한이 없습니다')
  })

  it('422 검증 오류는 문제가 된 입력 칸을 알려 준다', () => {
    const detail = [{ loc: ['body', 'name'], msg: 'Field required' }]
    expect(errorCause(httpError(422, detail))).toContain('name')
  })

  it('502~504는 서버가 응답하지 않는다고 알린다', () => {
    expect(errorCause(httpError(503))).toContain('서버가 응답하지 않습니다')
  })

  it('500은 서버 내부 오류와 상태 코드를 알린다', () => {
    const cause = errorCause(httpError(500))
    expect(cause).toContain('서버에서 오류')
    expect(cause).toContain('500')
  })

  it('로그인 만료(401)를 알린다', () => {
    expect(errorCause(httpError(401))).toContain('로그인')
  })

  it('한국어 메시지를 가진 일반 Error는 그 메시지를 쓴다', () => {
    expect(errorCause(new Error('PDF를 받지 못했습니다'))).toBe('PDF를 받지 못했습니다')
  })

  it('알 수 없는 값이면 빈 문자열이 아니라 일반 안내를 준다', () => {
    expect(errorCause(undefined)).not.toBe('')
  })
})

describe('explainFailure', () => {
  it('비어 있으면 원인을 모른다고 알리고 할 일을 안내한다', () => {
    expect(explainFailure(null)).toContain('원인이 기록되지 않았습니다')
  })

  it('한국어 메시지는 그대로 쓴다', () => {
    expect(explainFailure('10분 안에 끝나지 않아 중단된 것으로 처리했습니다')).toBe('10분 안에 끝나지 않아 중단된 것으로 처리했습니다')
  })

  it('시간 초과를 알아본다', () => {
    expect(explainFailure('ReadTimeout: timed out')).toContain('시간이 초과')
  })

  it('모델 서버 연결 실패를 알아본다', () => {
    expect(explainFailure('ConnectError: [Errno 111] Connection refused')).toContain('연결하지 못했습니다')
  })

  it('API 키 문제를 알아본다', () => {
    expect(explainFailure('AuthenticationError: Incorrect API key provided')).toContain('API 키')
  })

  it('사용 한도 초과를 알아본다', () => {
    expect(explainFailure('RateLimitError: 429 Too Many Requests')).toContain('한도')
  })

  it('GPU 메모리 부족을 알아본다', () => {
    expect(explainFailure('torch.OutOfMemoryError: CUDA out of memory')).toContain('메모리')
  })

  it('모르는 영어 메시지는 원문을 붙이고 관리자 안내를 준다', () => {
    const text = explainFailure('KeyError: foo')
    expect(text).toContain('KeyError: foo')
    expect(text).toContain('관리자')
  })
})

describe('describeError', () => {
  it('무엇을 못 했는지와 원인을 한 문장씩 잇는다', () => {
    const text = describeError(httpError(403, 'Access denied'), '그룹 목록을 불러오지 못했습니다.')
    expect(text.startsWith('그룹 목록을 불러오지 못했습니다.')).toBe(true)
    expect(text).toContain('권한이 없습니다')
  })

  it('apiErrorDetail도 같은 결과를 준다(기존 호출 호환)', () => {
    const error = httpError(404, 'Collection not found')
    expect(apiErrorDetail(error, '저장하지 못했습니다.')).toBe(describeError(error, '저장하지 못했습니다.'))
  })
})
