import type { SignalEntry } from '../types'

function signalBadge(status: string) {
  const s = status.toLowerCase()
  if (s === 'entered') return <span className="badge badge-entered">entered</span>
  if (s === 'watching') return <span className="badge badge-watching">watching</span>
  if (s === 'error') return <span className="badge badge-error">error</span>
  if (s === 'halted') return <span className="badge badge-error">halted</span>
  if (s === 'no_signal') return <span className="badge badge-no-signal">no signal</span>
  if (s === 'skipped') return <span className="badge badge-skipped">skipped</span>
  return <span className="badge badge-closed">{status}</span>
}

interface Props {
  signals: SignalEntry[]
}

export default function SignalLogTable({ signals }: Props) {
  if (!signals.length) {
    return (
      <div className="table-scroll"><table>
        <thead><tr><th>Time</th><th>Pair</th><th>Dir</th><th>Status</th><th>Reason</th></tr></thead>
        <tbody><tr className="empty-row"><td colSpan={5}>No signal history</td></tr></tbody>
      </table></div>
    )
  }

  return (
    <div className="table-scroll"><table>
      <thead><tr><th>Time</th><th>Pair</th><th>Dir</th><th>Status</th><th>Reason</th></tr></thead>
      <tbody>
        {signals.map((sig, i) => (
          <tr key={i}>
            <td className="mono">{sig.evaluated_at?.substring(11, 19) ?? '—'}</td>
            <td>{(sig.pair ?? '—').replace('_', '/')}</td>
            <td>{(sig.direction ?? '—').toUpperCase()}</td>
            <td>{signalBadge(sig.status)}</td>
            <td>{sig.reason ?? '—'}</td>
          </tr>
        ))}
      </tbody>
    </table></div>
  )
}
