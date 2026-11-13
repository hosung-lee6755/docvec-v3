import { describe, it, expect } from 'vitest'
import { ACCOUNT_CSV_TEMPLATE, issuedAccountsCsv } from './accountCsv'

describe('accountCsv', () => {
  it('template starts with the headers the server accepts', () => {
    expect(ACCOUNT_CSV_TEMPLATE.split('\n')[0]).toBe('﻿이메일,이름,역할,열람등급,그룹')
  })

  it('result csv quotes cells that hold commas or quotes', () => {
    const csv = issuedAccountsCsv([
      { email: 'a@x.com', username: '김, 직원', role: 'viewer', groups: ['영업팀', '기획팀'], temporary_password: 'p"w1' },
    ])
    expect(csv.split('\n')[1]).toBe('a@x.com,"김, 직원",viewer,영업팀;기획팀,"p""w1"')
  })
})
