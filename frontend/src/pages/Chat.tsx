import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChatInput } from '../components/chat/ChatInput'
import { MessageBubble } from '../components/chat/MessageBubble'
import { ConfirmModal } from '../components/ConfirmModal'
import { CrisisFlow } from '../components/crisis/CrisisFlow'
import { useChat } from '../hooks/useChat'

export function Chat() {
  const navigate = useNavigate()
  const { messages, busy, crisis, send, retry } = useChat()
  const [dismissedCrisis, setDismissedCrisis] = useState<string | null>(null)
  const [confirmingEnd, setConfirmingEnd] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages])

  const leave = () => navigate('/', { replace: true })

  return (
    <div className="flex h-dvh flex-col">
      <header className="flex items-center justify-between px-4 pt-5 pb-2.5">
        <button type="button" onClick={leave} aria-label="뒤로" className="text-[20px]/[normal]">
          ‹
        </button>
        <h1 className="text-[14px]/[normal] font-bold">대화</h1>
        <button
          type="button"
          onClick={() => setConfirmingEnd(true)}
          className="rounded-[20px] border border-line bg-white px-3 py-1.5 text-[11px]/[normal] text-muted"
        >
          대화 종료
        </button>
      </header>

      <main className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-4 pt-1.5 pb-3" aria-live="polite">
        {messages.map((m) => (
          <MessageBubble
            key={m.id}
            role={m.role}
            failed={m.status === 'failed'}
            onRetry={() => retry(m.id)}
          >
            {m.content}
          </MessageBubble>
        ))}
        <div ref={bottomRef} />
      </main>

      <ChatInput disabled={busy} onSend={send} />

      {crisis && crisis.messageId !== dismissedCrisis && (
        <CrisisFlow resources={crisis.resources} onClose={() => setDismissedCrisis(crisis.messageId)} />
      )}

      {confirmingEnd && (
        <ConfirmModal
          title="대화를 종료할까요?"
          description="지금까지 나눈 이야기는 기록 저장 동의 여부에 따라 보관돼요."
          confirmLabel="종료하기"
          onCancel={() => setConfirmingEnd(false)}
          onConfirm={leave}
        />
      )}
    </div>
  )
}
