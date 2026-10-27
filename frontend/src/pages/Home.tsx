import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { listConversations, type ConversationSummary } from '../api/conversations'
import { Mascot } from '../components/Mascot'
import { TabBar } from '../components/TabBar'

const formatDate = (iso: string) => iso.replaceAll('-', '.')

export function Home() {
  const [records, setRecords] = useState<ConversationSummary[]>([])

  useEffect(() => {
    listConversations().then(setRecords)
  }, [])

  return (
    <div className="flex min-h-dvh flex-col">
      <main className="flex flex-1 flex-col gap-[18px] px-5 pt-10 pb-4">
        <header className="flex items-center gap-2">
          <div className="flex flex-1 flex-col gap-1">
            <h1 className="text-lg font-bold">오늘은 어떤 하루였나요</h1>
            <p className="text-[11.5px] text-muted">마음이 복잡할 때, 잠시 정리해볼까요</p>
          </div>
          <Mascot variant="waving" width={56} height={68} />
        </header>

        <Link
          to="/chat"
          className="flex flex-col items-center justify-center gap-2 rounded-hero bg-primary py-8 text-white shadow-card"
        >
          <span className="text-[26px]" aria-hidden>
            💬
          </span>
          <span className="text-base font-bold">대화 시작하기</span>
        </Link>

        <h2 className="text-[13px] font-bold text-muted">최근 기록</h2>
        <ul className="flex flex-col gap-[18px]">
          {records.map((record) => (
            <li key={record.id}>
              <Link
                to={`/records/${record.id}`}
                className="flex items-center gap-2 rounded-card bg-white px-3.5 py-3 shadow-card"
              >
                <span className="flex flex-1 flex-col gap-0.5">
                  <span className="text-[12.5px]">{record.title}</span>
                  <span className="text-[10.5px] text-muted">{formatDate(record.createdAt)}</span>
                </span>
                <span className="text-[15px] text-muted" aria-hidden>
                  ›
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </main>
      <TabBar />
    </div>
  )
}
