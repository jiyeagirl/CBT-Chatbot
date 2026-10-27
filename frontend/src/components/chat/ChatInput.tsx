import { useState, type FormEvent } from 'react'

type ChatInputProps = {
  disabled?: boolean
  onSend: (text: string) => void
}

export function ChatInput({ disabled, onSend }: ChatInputProps) {
  const [text, setText] = useState('')

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (disabled || !text.trim()) return
    onSend(text)
    setText('')
  }

  return (
    <form onSubmit={submit} className="flex items-center gap-2 bg-white px-4 py-2.5">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="메시지를 입력하세요"
        aria-label="메시지 입력"
        className="min-w-0 flex-1 rounded-3xl bg-white px-4 py-3 text-[12.5px]/[normal] shadow-card outline-none placeholder:text-placeholder focus-visible:ring-2 focus-visible:ring-primary/40"
      />
      <button
        type="submit"
        aria-label="보내기"
        disabled={disabled || !text.trim()}
        className="flex size-[42px] shrink-0 items-center justify-center rounded-[21px] bg-primary text-[17px]/[normal] font-bold text-white disabled:opacity-40"
      >
        ↑
      </button>
    </form>
  )
}
