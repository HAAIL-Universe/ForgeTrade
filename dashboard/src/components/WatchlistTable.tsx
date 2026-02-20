import { fmtPrice } from '../helpers'
import type { PendingSignal } from '../types'

interface Props {
  signal: PendingSignal | null
}

export default function WatchlistTable({ signal }: Props) {
  if (!signal || signal.status === 'no_signal') {
    return (
      <div className="table-scroll"><table>
        <thead><tr><th>Pair</th><th>Dir</th><th>Zone</th><th>Reason</th><th>Status</th></tr></thead>
        <tbody><tr className="empty-row"><td colSpan={5}>No pending signals</td></tr></tbody>
      </table></div>
    )
  }

  return (
    <div className="table-scroll"><table>
      <thead><tr><th>Pair</th><th>Dir</th><th>Zone</th><th>Reason</th><th>Status</th></tr></thead>
      <tbody>
        <tr>
          <td>{(signal.pair ?? '—').replace('_', '/')}</td>
          <td>{(signal.direction ?? '—').toUpperCase()}</td>
          <td className="mono">{fmtPrice(signal.zone_price)}</td>
          <td>{signal.reason ?? '—'}</td>
          <td>{signal.status ?? '—'}</td>
        </tr>
      </tbody>
    </table></div>
  )
}
