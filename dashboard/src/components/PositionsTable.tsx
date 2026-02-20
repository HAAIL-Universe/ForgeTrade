import { fmtPrice, fmtDateTime, fmt$, pnlClass } from '../helpers'
import type { Position } from '../types'

interface Props {
  positions: Position[]
}

export default function PositionsTable({ positions }: Props) {
  if (!positions.length) {
    return (
      <table>
        <thead><tr><th>Pair</th><th>Dir</th><th>Units</th><th>Entry</th><th>SL</th><th>TP</th><th>Opened</th><th>uP&L</th></tr></thead>
        <tbody><tr className="empty-row"><td colSpan={8}>No open positions</td></tr></tbody>
      </table>
    )
  }

  return (
    <table>
      <thead><tr><th>Pair</th><th>Dir</th><th>Units</th><th>Entry</th><th>SL</th><th>TP</th><th>Opened</th><th>uP&L</th></tr></thead>
      <tbody>
        {positions.map((p, i) => {
          const digits = p.instrument?.indexOf('XAU') >= 0 ? 2 : 5
          return (
            <tr key={i}>
              <td>{(p.instrument ?? '—').replace('_', '/')}</td>
              <td>{(p.direction ?? '—').toUpperCase()}</td>
              <td className="mono">{p.units ?? 0}</td>
              <td className="mono">{fmtPrice(p.avg_price, digits)}</td>
              <td className="mono">{fmtPrice(p.stop_loss, digits)}</td>
              <td className="mono">{fmtPrice(p.take_profit, digits)}</td>
              <td className="mono">{fmtDateTime(p.open_time)}</td>
              <td className={`mono ${pnlClass(p.unrealized_pnl)}`}>{fmt$(p.unrealized_pnl)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
