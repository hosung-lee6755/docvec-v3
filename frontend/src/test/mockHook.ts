import { vi } from 'vitest'

/**
 * 훅/함수 목의 반환값을 "테스트가 쓰는 필드만" 채워 지정한다.
 *
 * 훅 반환 타입 전체(예: UseQueryResult)를 만들 필요는 없지만, 목 대상 함수는 실제
 * 시그니처에서 추론하므로 존재하지 않는 훅을 목킹하면 컴파일 단계에서 걸린다.
 */
export function mockHook<Args extends unknown[], Result>(
  fn: (...args: Args) => Result,
  value: Partial<Record<keyof Result, unknown>> | Record<string, unknown>,
): void {
  vi.mocked(fn).mockReturnValue(value as Result)
}
