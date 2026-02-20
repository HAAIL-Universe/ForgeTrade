import { useState, useEffect } from 'react'
import type { StreamStatus, Position } from '../types'

interface Props {
  mode: string
  startedAt: string | null
  circuitBreakerActive: boolean
  positions: Position[]
}

export function Header({ mode, startedAt, circuitBreakerActive, positions }: Props) {
  const m = mode.toLowerCase()
  const badgeCls = `mode-badge mode-${m === 'paper' || m === 'live' || m === 'backtest' ? m : 'idle'}`

  // Live uptime counter
  const [uptimeStr, setUptimeStr] = useState('\u25B2 0h0m')
  useEffect(() => {
    if (!startedAt) { setUptimeStr('\u25B2 0h0m'); return }
    const t0 = new Date(startedAt).getTime()
    const tick = () => {
      const secs = Math.max(0, Math.floor((Date.now() - t0) / 1000))
      const h = Math.floor(secs / 3600)
      const mn = Math.floor((secs % 3600) / 60)
      setUptimeStr(`\u25B2 ${h}h${mn}m`)
    }
    tick()
    const id = setInterval(tick, 60_000)
    return () => clearInterval(id)
  }, [startedAt])

  // Open position pair chips
  const openPairs = positions.map(p => (p.instrument ?? '').replace('_', '/'))

  return (
    <div className="header">
      <h1>FORGETRADE</h1>
      <div className="header-right">
        {openPairs.length > 0 && (
          <div className="header-pairs">
            {openPairs.map((pair, i) => (
              <span key={i} className="pair-chip">{pair}</span>
            ))}
          </div>
        )}
        {circuitBreakerActive
          ? <span className="cb-badge cb-active">\u25CF CIRCUIT BREAKER</span>
          : <span className="cb-badge cb-off">\u25CF CB OFF</span>
        }
        <span className={badgeCls}>{mode.toUpperCase()}</span>
        <span className="uptime mono">{uptimeStr}</span>
      </div>
    </div>
  )
}

export function pickFirstActive(streams: Record<string, StreamStatus>): StreamStatus | null {
  const keys = Object.keys(streams)
  for (const k of keys) {
    if (streams[k].running) return streams[k]
  }
  return keys.length ? streams[keys[0]] : null
}
