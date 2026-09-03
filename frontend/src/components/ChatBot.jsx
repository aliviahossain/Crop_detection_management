import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { useLang, useT } from '../lib/i18n.js'

// A chat bubble cradling a sprout -- ties the floating assistant to the crop
// theme instead of a generic "?" so it reads as *this* app's helper.
function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" width="26" height="26" aria-hidden="true" focusable="false">
      <path
        fill="currentColor"
        d="M12 2.6c-5.2 0-9.4 3.5-9.4 7.9 0 2.5 1.4 4.7 3.5 6.1v3.4c0 .5.6.8 1 .5l3-2.1c.6.1 1.2.2 1.9.2 5.2 0 9.4-3.5 9.4-7.9S17.2 2.6 12 2.6Z"
      />
      <path
        fill="none"
        stroke="#fff"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12 14.2v-3.1m0 0c0-1.3-1.1-2.4-2.5-2.4m2.5 2.4c0-1.5 1.2-2.7 2.7-2.7"
      />
    </svg>
  )
}

export default function ChatBot() {
  const t = useT()
  const { lang } = useLang()
  const [open, setOpen] = useState(false)
  const [messages, setMessages] = useState([]) // { role, content }
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const scrollRef = useRef(null)
  const inputRef = useRef(null)

  // Greet on first open, in the language active at that moment.
  useEffect(() => {
    if (open && messages.length === 0) {
      setMessages([{ role: 'assistant', content: t('chat.greeting') }])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // Keep the newest message and, once opened, the input in view.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy])
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  async function send() {
    const text = input.trim()
    if (!text || busy) return
    const history = messages.filter((m) => m.content !== t('chat.error'))
    const next = [...messages, { role: 'user', content: text }]
    setMessages(next)
    setInput('')
    setBusy(true)
    try {
      const res = await api.chat({ message: text, history, language: lang })
      setMessages((m) => [...m, { role: 'assistant', content: res.reply }])
    } catch {
      setMessages((m) => [...m, { role: 'assistant', content: t('chat.error') }])
    } finally {
      setBusy(false)
    }
  }

  function onKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <>
      {open && (
        <section className="chat-panel" role="dialog" aria-label={t('chat.title')}>
          <header className="chat-head">
            <span className="chat-head-icon" aria-hidden="true">
              <ChatIcon />
            </span>
            <div className="chat-head-text">
              <strong>{t('chat.title')}</strong>
              <small>{t('chat.subtitle')}</small>
            </div>
            <button className="chat-x" onClick={() => setOpen(false)} aria-label={t('chat.close')}>
              ✕
            </button>
          </header>

          <div className="chat-log" ref={scrollRef}>
            {messages.map((m, i) => (
              <div key={i} className={`chat-msg ${m.role}`}>
                {m.content}
              </div>
            ))}
            {busy && (
              <div className="chat-msg assistant chat-typing" aria-live="polite">
                <span />
                <span />
                <span />
              </div>
            )}
          </div>

          <div className="chat-input">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKeyDown}
              placeholder={t('chat.placeholder')}
              aria-label={t('chat.placeholder')}
            />
            <button onClick={send} disabled={busy || !input.trim()} aria-label={t('chat.send')}>
              ➤
            </button>
          </div>
        </section>
      )}

      <button
        className={`chat-fab${open ? ' open' : ''}`}
        onClick={() => setOpen((o) => !o)}
        aria-label={open ? t('chat.close') : t('chat.open')}
        aria-expanded={open}
      >
        {open ? <span className="chat-fab-x" aria-hidden="true">✕</span> : <ChatIcon />}
      </button>
    </>
  )
}
