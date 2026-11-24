import { Link } from 'react-router-dom'
import type { PlanSession } from '../../api/plans'
import { formatMonthDay, summarySentences } from '../../lib/format'

type SessionTimelineProps = {
  sessions: PlanSession[]
  total: number
}

// 회기 타임라인: 1회기부터 세로선으로 잇고, 마친 회기에는 날짜와 요약 첫 문장을 붙인다.
// 아직 하지 않은 회기는 흐린 점으로 남은 길을 보여준다. 마친 회기를 누르면 그 회기 화면으로 간다.
export function SessionTimeline({ sessions, total }: SessionTimelineProps) {
  if (sessions.length === 0) return null
  const byNumber = new Map(sessions.map((s) => [s.number, s]))
  const nextNo = sessions.length + 1

  return (
    <nav aria-label="마친 회기" className="flex flex-col gap-2">
      <h2 className="px-1 pt-1.5 text-[13px]/[normal] font-bold text-muted">회기 타임라인</h2>
      <ol className="rounded-xl bg-white px-4 py-4 shadow-card">
        {Array.from({ length: total }, (_, i) => {
          const no = i + 1
          const session = byNumber.get(no)
          const last = no === total
          return (
            <li key={no} className="relative flex gap-3">
              {!last && (
                <span
                  aria-hidden
                  className={`absolute top-8 bottom-0 left-[15px] w-0.5 ${
                    session && byNumber.has(no + 1) ? 'bg-primary/40' : 'bg-line'
                  }`}
                />
              )}
              <span
                aria-hidden
                className={`relative z-10 flex size-8 shrink-0 items-center justify-center rounded-full text-[12px] font-bold ${
                  session
                    ? 'bg-primary text-white'
                    : no === nextNo
                      ? 'border-2 border-dashed border-primary/60 bg-white text-primary'
                      : 'bg-surface-muted text-muted'
                }`}
              >
                {no}
              </span>
              <div className={`min-w-0 flex-1 ${last ? '' : 'pb-5'}`}>
                {session ? <TimelineEntry session={session} /> : <Upcoming no={no} next={no === nextNo} />}
              </div>
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

function TimelineEntry({ session }: { session: PlanSession }) {
  const headline = summarySentences(session.summary)[0]
  return (
    <Link to={`/plan/session/${session.conversationId}`} className="flex flex-col gap-1 pt-1">
      <span className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[13px]/[16px] font-bold">{session.title ?? `${session.number}회기 상담`}</span>
        <span className="shrink-0 text-[10.5px]/[13px] text-muted">{formatMonthDay(session.completedAt)} ›</span>
      </span>
      {session.summaryStatus === 'done' && headline ? (
        <span className="line-clamp-2 text-[12px]/[1.6] text-muted">{headline}</span>
      ) : session.summaryStatus === 'failed' ? (
        <span className="text-[11.5px]/[1.5] text-muted">요약을 만들지 못했어요</span>
      ) : (
        <span className="text-[11.5px]/[1.5] text-muted">요약 정리 중…</span>
      )}
    </Link>
  )
}

function Upcoming({ no, next }: { no: number; next: boolean }) {
  return (
    <p className={`pt-1.5 text-[12px]/[16px] ${next ? 'font-bold text-primary' : 'text-muted'}`}>
      {next ? `${no}회기 · 다음 차례` : `${no}회기`}
    </p>
  )
}
