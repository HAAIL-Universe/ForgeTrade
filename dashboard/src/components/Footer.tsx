import { useState, useEffect } from 'react'

interface Props {
  lastUpdated: number  // epoch ms from the most recent successful poll
}

export default function Footer({ lastUpdated }: Props) {
  const [pulse, setPulse] = useState(false)
  const [ago, setAgo] = useState('')

  // Flash the pulse dot on each update
  useEffect(() => {
    if (!lastUpdated) return
    setPulse(true)
    const id = setTimeout(() => setPulse(false), 600)
    return () => clearTimeout(id)
  }, [lastUpdated])

  // Update "Xm Xs ago" every second
  useEffect(() => {
    const tick = () => {
      if (!lastUpdated) { setAgo('—'); return }
      const diff = Math.max(0, Math.floor((Date.now() - lastUpdated) / 1000))
      if (diff < 2) setAgo('just now')
      else if (diff < 60) setAgo(`${diff}s ago`)
      else setAgo(`${Math.floor(diff / 60)}m ${diff % 60}s ago`)
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [lastUpdated])

  return (
    <div className="footer">
      <span className={`pulse-dot${pulse ? ' active' : ''}`} />
      Last update: <span className="mono">{ago}</span> &nbsp;|&nbsp; Polling: every 5s
    </div>
  )
}
