import { describe, expect, it } from 'vitest'
import { documentTypeLabel, resolveUploadDocumentType } from './documentTypes'

describe('documentTypes', () => {
  it('uses the file type first, then the batch type, then leaves it to the server', () => {
    expect(resolveUploadDocumentType('general', 'regulation')).toBe('general')
    expect(resolveUploadDocumentType('', 'regulation')).toBe('regulation')
    expect(resolveUploadDocumentType(undefined, '')).toBeUndefined()
  })

  it('labels known types only', () => {
    expect(documentTypeLabel('regulation')).toBe('규정·법령')
    expect(documentTypeLabel(null)).toBeNull()
    expect(documentTypeLabel('contract')).toBeNull()
  })
})
