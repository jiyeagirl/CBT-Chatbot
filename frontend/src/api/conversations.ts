// docs/api-spec.md 의 GET /conversations 에 대응한다.
// 백엔드가 준비되기 전까지는 목업 데이터를 돌려주며, 실제 API 연동 시 이 파일만 교체한다.

export type ConversationSummary = {
  id: string
  title: string
  createdAt: string
}

const mockConversations: ConversationSummary[] = [
  { id: 'c-2', title: '발표 자료 오타 관련 생각 정리', createdAt: '2025-03-12' },
  { id: 'c-1', title: '친구와의 약속 취소, 마음이 쓰였던 날', createdAt: '2025-03-09' },
]

export async function listConversations(): Promise<ConversationSummary[]> {
  return mockConversations
}
