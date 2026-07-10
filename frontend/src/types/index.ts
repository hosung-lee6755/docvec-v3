export interface User {
  id: string
  email: string
  role: string
  created_at: string
}

export interface SearchResult {
  chunk_id: string
  score: number
  document_id: string
  content: string
  metadata: Record<string, unknown>
}

export interface DashboardStats {
  total_documents: number
  processing: number
  indexed: number
  collections: number
}
