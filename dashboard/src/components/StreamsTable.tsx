import { fmtTime, instrumentLabel, instrumentCategory } from '../helpers'
import { api } from '../api'
import type { StreamStatus } from '../types'

interface Props {
  streams: Record<string, StreamStatus>
  activeTab: string | null
  onSelectStream: (name: string) => void
}

/** Map strategy key → short display label */
function strategyLabel(s: StreamStatus): string {
  const strat = s.strategy ?? ''
  if (strat === 'trend_scalp') return 'Scalp'
  if (strat === 'mean_reversion') return 'MR'
  if (strat === 'sr_rejection') return 'SR Swing'
  // Fallback: use stream name
  return s.stream_name ?? '—'
}

export default function StreamsTable({ streams, activeTab, onSelectStream }: Props) {
  const keys = Object.keys(streams)

  if (!keys.length) {
    return (
      <table>
        <thead><tr><th>Strategy</th><th>Instrument</th><th>Status</th><th>Last Signal</th><th></th></tr></thead>
        <tbody><tr className="empty-row"><td colSpan={5}>No streams configured</td></tr></tbody>
      </table>
    )
  }

  const handlePause = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation()
    await api.pauseStream(name)
  }

  const handleResume = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation()
    await api.resumeStream(name)
  }

  return (
    <table>
      <thead><tr><th>Strategy</th><th>Instrument</th><th>Status</th><th>Last Signal</th><th></th></tr></thead>
      <tbody>
        {keys.map(k => {
          const s = streams[k]
          const pair = s.pair ?? '—'
          const isActive = s.running
          const dotClass = isActive ? 'dot-active' : 'dot-off'
          const sel = activeTab === k ? ' stream-selected' : ''
          const modeLabel = s.mode === 'paused' ? 'paused'
            : s.mode === 'stopped' ? 'stopped'
            : isActive ? 'active' : 'off'

          return (
            <tr key={k} className={`stream-row${sel}`} onClick={() => onSelectStream(k)}>
              <td>{strategyLabel(s)}</td>
              <td className="mono">
                {instrumentLabel(pair)}
                <span className="stream-category">{instrumentCategory(pair)}</span>
              </td>
              <td><span className={`dot ${dotClass}`} />{modeLabel}</td>
              <td className="mono">{s.last_signal_time ? fmtTime(s.last_signal_time) : '—'}</td>
              <td className="stream-actions">
                {isActive ? (
                  <button
                    className="stream-btn stream-btn-pause"
                    title="Pause this stream"
                    onClick={(e) => handlePause(e, k)}
                  >⏸</button>
                ) : (
                  <button
                    className="stream-btn stream-btn-resume"
                    title="Resume this stream"
                    onClick={(e) => handleResume(e, k)}
                  >▶</button>
                )}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
