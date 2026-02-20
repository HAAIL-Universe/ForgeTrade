import { useState } from 'react'
import { fmtPrice, fmtDateTime, fmtDuration, fmt$, pnlClass } from '../helpers'
import type { ClosedTrade } from '../types'

function closeReasonBadge(reason: string | null) {
  if (!reason) return <span className="badge badge-closed">closed</span>
  const r = reason.toUpperCase()
  if (r.includes('TAKE_PROFIT')) return <span className="badge badge-tp">TP hit</span>
  if (r.includes('STOP_LOSS')) return <span className="badge badge-sl">SL hit</span>
  if (r.includes('TRAILING')) return <span className="badge badge-sl">trail</span>
  if (r.includes('CLIENT') || r.includes('MARKET_ORDER')) return <span className="badge badge-manual">manual</span>
  return <span className="badge badge-closed">{reason.toLowerCase()}</span>
}

interface Props {
  trades: ClosedTrade[]
}

export default function TradeHistoryTable({ trades }: Props) {
  const [filter, setFilter] = useState<string>('ALL')

  // Derive unique instruments for filter pills
  const instruments = Array.from(new Set(trades.map(t => t.pair).filter(Boolean)))
  instruments.sort()

  // Apply filter
  const filtered = filter === 'ALL'
    ? trades
    : filter === 'BOT'
      ? trades.filter(t => t.stop_loss != null || t.take_profit != null)
      : trades.filter(t => t.pair === filter)

  // Totals for the filtered view
  const filteredPnl = filtered.reduce((sum, t) => sum + (t.pnl ?? 0), 0)

  return (
    <>
      <div className="trade-filters">
        <button
          className={`filter-pill${filter === 'ALL' ? ' active' : ''}`}
          onClick={() => setFilter('ALL')}
        >All</button>
        <button
          className={`filter-pill${filter === 'BOT' ? ' active' : ''}`}
          onClick={() => setFilter('BOT')}
          title="Trades with SL/TP set (bot-placed)"
        >Bot only</button>
        {instruments.map(inst => (
          <button
            key={inst}
            className={`filter-pill${filter === inst ? ' active' : ''}`}
            onClick={() => setFilter(inst)}
          >{(inst ?? '').replace('_', '/')}</button>
        ))}
        {filter !== 'ALL' && (
          <span className={`filter-total mono ${filteredPnl >= 0 ? 'positive' : 'negative'}`}>
            {fmt$(filteredPnl)}
          </span>
        )}
      </div>
      <div className="table-scroll"><table>
        <thead><tr><th>Pair</th><th>Dir</th><th>Units</th><th>Entry</th><th>Exit</th><th>SL</th><th>TP</th><th>P&L</th><th>Reason</th><th>Duration</th><th>Closed</th></tr></thead>
        <tbody>
          {filtered.length === 0 ? (
            <tr className="empty-row"><td colSpan={11}>No trades{filter !== 'ALL' ? ` for ${filter.replace('_', '/')}` : ''}</td></tr>
          ) : (
            filtered.map((t, i) => {
              const digits = t.pair?.indexOf('XAU') >= 0 ? 2 : 5
              return (
                <tr key={i}>
                  <td>{(t.pair ?? '—').replace('_', '/')}</td>
                  <td>{(t.direction ?? '—').toUpperCase()}</td>
                  <td className="mono">{t.units != null ? Math.abs(t.units).toLocaleString() : '—'}</td>
                  <td className="mono">{fmtPrice(t.entry_price, digits)}</td>
                  <td className="mono">{fmtPrice(t.exit_price, digits)}</td>
                  <td className="mono">{fmtPrice(t.stop_loss, digits)}</td>
                  <td className="mono">{fmtPrice(t.take_profit, digits)}</td>
                  <td className={`mono ${pnlClass(t.pnl)}`}>{fmt$(t.pnl)}</td>
                  <td>{closeReasonBadge(t.close_reason)}</td>
                  <td className="mono">{fmtDuration(t.opened_at, t.closed_at)}</td>
                  <td className="mono">{fmtDateTime(t.closed_at)}</td>
                </tr>
              )
            })
          )}
        </tbody>
      </table></div>
    </>
  )
}
