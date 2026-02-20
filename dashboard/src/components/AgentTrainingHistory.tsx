import { useState, useEffect } from 'react'
import type { TrainingEntry } from '../types'

interface Props {
  entries: TrainingEntry[]
}

export default function AgentTrainingHistory({ entries }: Props) {
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null)

  // Auto-select latest
  useEffect(() => {
    if (entries.length > 0 && selectedIdx === null) {
      setSelectedIdx(entries.length - 1)
    }
  }, [entries.length, selectedIdx])

  if (entries.length === 0) {
    return (
      <div className="training-empty">
        <div className="training-empty-icon">🧪</div>
        <div className="training-empty-text">No evaluations yet</div>
        <div className="training-empty-hint">
          Run <code>python -m scripts.eval_agent</code> after training to start tracking progress
        </div>
      </div>
    )
  }

  const latest = entries[entries.length - 1]
  const selected = selectedIdx !== null ? entries[selectedIdx] : latest

  // Compute deltas from first→latest
  const first = entries[0]
  const deltaWin = latest.metrics.win_rate - first.metrics.win_rate
  const deltaR = latest.metrics.avg_r_multiple - first.metrics.avg_r_multiple
  const deltaPF = latest.metrics.profit_factor - first.metrics.profit_factor
  const deltaSharpe = latest.metrics.sharpe_ratio - first.metrics.sharpe_ratio

  return (
    <div className="training-history">
      {/* Summary header */}
      <div className="training-summary">
        <SummaryCard
          label="Win Rate"
          value={`${(latest.metrics.win_rate * 100).toFixed(1)}%`}
          delta={entries.length > 1 ? deltaWin * 100 : null}
          unit="%"
          good={deltaWin > 0}
        />
        <SummaryCard
          label="Avg R"
          value={latest.metrics.avg_r_multiple.toFixed(3)}
          delta={entries.length > 1 ? deltaR : null}
          good={deltaR > 0}
        />
        <SummaryCard
          label="Profit Factor"
          value={latest.metrics.profit_factor.toFixed(2)}
          delta={entries.length > 1 ? deltaPF : null}
          good={deltaPF > 0}
        />
        <SummaryCard
          label="Sharpe"
          value={formatSharpe(latest.metrics.sharpe_ratio)}
          delta={entries.length > 1 ? deltaSharpe : null}
          good={deltaSharpe > 0}
        />
      </div>

      {/* Progress over time — horizontal bar chart for key metrics */}
      {entries.length > 1 && (
        <div className="training-progress">
          <div className="training-progress-title">Progress Over Evaluations</div>
          <div className="training-bars">
            {entries.map((e, i) => {
              const wr = e.metrics.win_rate * 100
              const isSelected = i === selectedIdx
              return (
                <div
                  key={i}
                  className={`training-bar-row ${isSelected ? 'selected' : ''}`}
                  onClick={() => setSelectedIdx(i)}
                  title={`${e.label}: ${wr.toFixed(1)}% win rate`}
                >
                  <span className="training-bar-label mono">{shortLabel(e.label)}</span>
                  <div className="training-bar-track">
                    <div
                      className={`training-bar-fill ${wr >= 50 ? 'bar-good' : wr >= 30 ? 'bar-mid' : 'bar-bad'}`}
                      style={{ width: `${Math.min(wr, 100)}%` }}
                    />
                  </div>
                  <span className="training-bar-value mono">{wr.toFixed(1)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Detail table for selected evaluation */}
      <div className="training-detail">
        <div className="training-detail-header">
          <span className="training-detail-title">{selected.label}</span>
          <span className="training-detail-time mono">{formatTimestamp(selected.timestamp)}</span>
        </div>
        <div className="training-detail-grid">
          <DetailRow label="Win Rate" value={`${(selected.metrics.win_rate * 100).toFixed(1)}%`} />
          <DetailRow label="Take Rate" value={`${(selected.metrics.take_rate * 100).toFixed(1)}%`} />
          <DetailRow label="Profit Factor" value={selected.metrics.profit_factor.toFixed(2)} />
          <DetailRow label="Avg R-Multiple" value={selected.metrics.avg_r_multiple.toFixed(4)} color={selected.metrics.avg_r_multiple >= 0 ? 'var(--green)' : 'var(--red)'} />
          <DetailRow label="Sharpe Ratio" value={formatSharpe(selected.metrics.sharpe_ratio)} />
          <DetailRow label="Max Drawdown" value={`${selected.metrics.max_drawdown.toFixed(1)}%`} color={selected.metrics.max_drawdown > 5 ? 'var(--red)' : undefined} />
          <DetailRow label="Mean Ep Reward" value={selected.metrics.mean_episode_reward.toFixed(3)} color={selected.metrics.mean_episode_reward >= 0 ? 'var(--green)' : 'var(--red)'} />
          <DetailRow label="Trades Taken" value={String(selected.metrics.total_trades_taken)} />
          <DetailRow label="Signals Seen" value={String(selected.metrics.total_signals_seen)} />
          <DetailRow label="Training Steps" value={selected.training_timesteps ? `${(selected.training_timesteps / 1000).toFixed(0)}K` : '—'} />
          <DetailRow label="Parameters" value={selected.parameters.toLocaleString()} />
          <DetailRow label="Eval Episodes" value={String(selected.eval_episodes)} />
        </div>
      </div>

      {/* Nudge info for selected entry */}
      {selected.nudge && (
        <div className="training-nudge">
          <div className="training-nudge-header">
            <span className="training-nudge-title">Parameter Nudge</span>
            {selected.nudge.reverted && <span className="training-nudge-badge reverted">REVERTED</span>}
          </div>
          <div className="training-nudge-body">
            <span className="training-nudge-param mono">{selected.nudge.param}</span>
            <span className="training-nudge-arrow">
              {selected.nudge.old_value} → {selected.nudge.new_value}
              {selected.nudge.direction > 0 ? ' ▲' : ' ▼'}
            </span>
          </div>
          <div className="training-nudge-reason">{selected.nudge.reason}</div>
        </div>
      )}

      {/* Failure clusters */}
      {selected.failures?.failure_clusters && selected.failures.failure_clusters.length > 0 && (
        <div className="training-failures">
          <div className="training-failures-title">Failure Clusters</div>
          <div className="training-failures-summary">
            <span>{selected.failures.losing_trades} / {selected.failures.total_trades} trades lost</span>
            {selected.failures.exit_reasons && (
              <span className="training-exit-reasons mono">
                {Object.entries(selected.failures.exit_reasons)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(' · ')}
              </span>
            )}
          </div>
          <div className="training-clusters">
            {selected.failures.failure_clusters.map((c, i) => (
              <div key={i} className="training-cluster">
                <div className="training-cluster-header">
                  <span className="training-cluster-pattern">{c.pattern.replace(/_/g, ' ')}</span>
                  <span className="training-cluster-impact mono">
                    {c.count} trades · {((c.count / (selected.failures?.losing_trades || 1)) * 100).toFixed(0)}% of losses
                  </span>
                </div>
                <div className="training-cluster-bar">
                  <div
                    className="training-cluster-fill"
                    style={{ width: `${Math.min(c.impact * 100, 100)}%` }}
                  />
                </div>
                <div className="training-cluster-suggestion">{c.suggestion}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Comparison table when multiple evals exist */}
      {entries.length > 1 && (
        <div className="training-comparison">
          <div className="training-comparison-title">All Evaluations</div>
          <table className="training-table">
            <thead>
              <tr>
                <th>Run</th>
                <th>Win%</th>
                <th>Take%</th>
                <th>PF</th>
                <th>Avg R</th>
                <th>DD%</th>
                <th>Reward</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e, i) => {
                const m = e.metrics
                const prev = i > 0 ? entries[i - 1].metrics : null
                return (
                  <tr
                    key={i}
                    className={i === selectedIdx ? 'row-selected' : ''}
                    onClick={() => setSelectedIdx(i)}
                  >
                    <td className="mono">{shortLabel(e.label)}</td>
                    <td className="mono">
                      {(m.win_rate * 100).toFixed(1)}
                      {prev && <TrendArrow current={m.win_rate} previous={prev.win_rate} />}
                    </td>
                    <td className="mono">{(m.take_rate * 100).toFixed(1)}</td>
                    <td className="mono">{m.profit_factor.toFixed(2)}</td>
                    <td className={`mono ${m.avg_r_multiple >= 0 ? 'positive' : 'negative'}`}>
                      {m.avg_r_multiple >= 0 ? '+' : ''}{m.avg_r_multiple.toFixed(3)}
                      {prev && <TrendArrow current={m.avg_r_multiple} previous={prev.avg_r_multiple} />}
                    </td>
                    <td className="mono">{m.max_drawdown.toFixed(1)}</td>
                    <td className={`mono ${m.mean_episode_reward >= 0 ? 'positive' : 'negative'}`}>
                      {m.mean_episode_reward >= 0 ? '+' : ''}{m.mean_episode_reward.toFixed(2)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ── Helpers ── */

function SummaryCard({ label, value, delta, unit, good }: {
  label: string; value: string; delta: number | null; unit?: string; good?: boolean
}) {
  return (
    <div className="training-sumcard">
      <div className="training-sumcard-label">{label}</div>
      <div className="training-sumcard-value mono">{value}</div>
      {delta !== null && (
        <div className={`training-sumcard-delta mono ${good ? 'positive' : 'negative'}`}>
          {delta >= 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(2)}{unit ?? ''}
        </div>
      )}
    </div>
  )
}

function DetailRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="training-detail-row">
      <span className="training-detail-label">{label}</span>
      <span className="training-detail-value mono" style={color ? { color } : undefined}>{value}</span>
    </div>
  )
}

function TrendArrow({ current, previous }: { current: number; previous: number }) {
  if (Math.abs(current - previous) < 0.0001) return null
  const up = current > previous
  return <span className={`trend-arrow ${up ? 'trend-up' : 'trend-down'}`}>{up ? '▲' : '▼'}</span>
}

function shortLabel(label: string): string {
  if (label.length > 16) return label.substring(0, 14) + '…'
  return label
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso.substring(0, 16)
  }
}

function formatSharpe(s: number): string {
  if (Math.abs(s) > 100000) return s > 0 ? '∞' : '-∞'
  return s.toFixed(2)
}
