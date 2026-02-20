import { useState } from 'react'
import type {
  StreamInsight,
  RLDecision,
  TrainingEntry,
  IterateStatus,
  IterateState,
  FailureCluster,
  NudgeInfo,
} from '../types'

type Tab = 'overview' | 'training' | 'failures' | 'nudges'

interface Props {
  agentInsight: StreamInsight | null
  rlDecisions: RLDecision[]
  trainingEntries: TrainingEntry[]
  iterateStatus: IterateStatus | null
  iterateState: IterateState | null
}

export default function ForgeAgent({
  agentInsight,
  rlDecisions,
  trainingEntries,
  iterateStatus,
  iterateState,
}: Props) {
  const [tab, setTab] = useState<Tab>('overview')

  const mode = agentInsight?.rl_mode ?? 'disabled'
  const latest = trainingEntries.length > 0 ? trainingEntries[trainingEntries.length - 1] : null
  const baseline = trainingEntries.length > 0 ? trainingEntries[0] : null

  return (
    <div className="fa">
      {/* Tab bar */}
      <div className="fa-tabs">
        {(['overview', 'training', 'failures', 'nudges'] as Tab[]).map(t => (
          <button
            key={t}
            className={`fa-tab ${tab === t ? 'fa-tab-active' : ''}`}
            onClick={() => setTab(t)}
          >
            {t === 'overview' ? 'Overview' : t === 'training' ? 'Training' : t === 'failures' ? 'Failures' : 'Nudges'}
            {t === 'failures' && latest?.failures?.failure_clusters?.length ? (
              <span className="fa-tab-badge">{latest.failures.failure_clusters.length}</span>
            ) : null}
            {t === 'training' && trainingEntries.length > 0 ? (
              <span className="fa-tab-badge">{trainingEntries.length}</span>
            ) : null}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {tab === 'overview' && (
        <OverviewTab
          mode={mode}
          agentInsight={agentInsight}
          rlDecisions={rlDecisions}
          latest={latest}
          baseline={baseline}
          iterateStatus={iterateStatus}
          iterateState={iterateState}
          totalEntries={trainingEntries.length}
        />
      )}
      {tab === 'training' && (
        <TrainingTab entries={trainingEntries} />
      )}
      {tab === 'failures' && (
        <FailuresTab entries={trainingEntries} />
      )}
      {tab === 'nudges' && (
        <NudgesTab iterateState={iterateState} entries={trainingEntries} />
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   OVERVIEW TAB
   ═══════════════════════════════════════════════════════════════════════ */

function OverviewTab({
  mode,
  agentInsight,
  rlDecisions,
  latest,
  baseline,
  iterateStatus,
  iterateState,
  totalEntries,
}: {
  mode: string
  agentInsight: StreamInsight | null
  rlDecisions: RLDecision[]
  latest: TrainingEntry | null
  baseline: TrainingEntry | null
  iterateStatus: IterateStatus | null
  iterateState: IterateState | null
  totalEntries: number
}) {
  const modeLabel = mode === 'active' ? 'ACTIVE' : mode === 'shadow' ? 'SHADOW' : 'OFF'
  const modeDot = mode === 'active' ? 'fa-dot-active' : mode === 'shadow' ? 'fa-dot-shadow' : 'fa-dot-off'

  const takes = rlDecisions.filter(d => d.action === 'TAKE').length
  const vetos = rlDecisions.filter(d => d.action === 'VETO').length
  const latestDecision = rlDecisions.length > 0 ? rlDecisions[rlDecisions.length - 1] : null

  // Iterate loop phase
  const phase = iterateStatus?.phase ?? 'idle'
  const phaseLabel = phase === 'training' ? 'Training…'
    : phase === 'evaluating' ? 'Evaluating…'
    : phase === 'nudging' ? 'Selecting nudge…'
    : phase === 'sleeping' ? 'Cooldown…'
    : phase === 'converged' ? 'Converged!'
    : 'Idle'
  const phaseClass = phase === 'converged' ? 'fa-phase-converged'
    : phase === 'idle' ? 'fa-phase-idle'
    : 'fa-phase-active'

  const iteration = iterateState?.iteration ?? 0
  const bestR = iterateState?.best_avg_r ?? null
  const bestIter = iterateState?.best_iteration ?? 0

  return (
    <div className="fa-overview">
      {/* Status row */}
      <div className="fa-status-row">
        <div className="fa-mode">
          <span className={`fa-dot ${modeDot}`} />
          <span className="fa-mode-label mono">{modeLabel}</span>
        </div>
        <div className={`fa-phase ${phaseClass}`}>
          <span className="fa-phase-pulse" />
          {phaseLabel}
        </div>
        {iteration > 0 && (
          <div className="fa-iteration mono">Iteration {iteration}</div>
        )}
      </div>

      {/* Key metrics grid */}
      <div className="fa-metrics-grid">
        <MiniStat
          label="Win Rate"
          value={latest ? `${(latest.metrics.win_rate * 100).toFixed(1)}%` : '—'}
          delta={baseline && latest && totalEntries > 1 ? (latest.metrics.win_rate - baseline.metrics.win_rate) * 100 : null}
          unit="%"
        />
        <MiniStat
          label="Avg R"
          value={latest ? fmtR(latest.metrics.avg_r_multiple) : '—'}
          delta={baseline && latest && totalEntries > 1 ? latest.metrics.avg_r_multiple - baseline.metrics.avg_r_multiple : null}
          color={latest && latest.metrics.avg_r_multiple >= 0 ? 'var(--green)' : 'var(--red)'}
        />
        <MiniStat
          label="Profit Factor"
          value={latest ? latest.metrics.profit_factor.toFixed(2) : '—'}
          delta={baseline && latest && totalEntries > 1 ? latest.metrics.profit_factor - baseline.metrics.profit_factor : null}
        />
        <MiniStat
          label="Take Rate"
          value={latest ? `${(latest.metrics.take_rate * 100).toFixed(1)}%` : '—'}
        />
        <MiniStat
          label="Best R"
          value={bestR != null && bestR > -900 ? fmtR(bestR) : '—'}
          sub={bestIter > 0 ? `iter ${bestIter}` : undefined}
        />
        <MiniStat
          label="Evaluations"
          value={String(totalEntries)}
        />
      </div>

      {/* Live decisions */}
      {rlDecisions.length > 0 && (
        <div className="fa-decisions">
          <div className="fa-section-title">
            Live Decisions
            <span className="fa-count mono">{rlDecisions.length} assessed · <span style={{ color: 'var(--green)' }}>{takes} take</span> · <span style={{ color: 'var(--red)' }}>{vetos} veto</span></span>
          </div>
          <div className="fa-decision-list">
            {[...rlDecisions].reverse().slice(0, 8).map((d, i) => (
              <div key={i} className="fa-decision-row">
                <span className="fa-dec-time mono">{d.timestamp.substring(11, 19)}</span>
                <span className={`fa-dec-action ${d.action === 'TAKE' ? 'fa-dec-take' : 'fa-dec-veto'}`}>
                  {d.action === 'TAKE' ? '✓' : '✗'} {d.action}
                </span>
                <span className="fa-dec-dir mono">{d.direction}</span>
                <span className="fa-dec-price mono">{d.entry_price}</span>
                <span className="fa-dec-conf mono" style={{ color: d.confidence >= 0.7 ? 'var(--green)' : d.confidence >= 0.55 ? 'var(--yellow)' : 'var(--red)' }}>
                  {Math.round(d.confidence * 100)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Iterate detail */}
      {iterateStatus?.detail && phase !== 'idle' && (
        <div className="fa-iterate-detail mono">{iterateStatus.detail}</div>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   TRAINING TAB
   ═══════════════════════════════════════════════════════════════════════ */

function TrainingTab({ entries }: { entries: TrainingEntry[] }) {
  const [selectedIdx, setSelectedIdx] = useState<number>(entries.length > 0 ? entries.length - 1 : 0)

  if (entries.length === 0) {
    return (
      <div className="fa-empty">
        <div className="fa-empty-icon">🧪</div>
        <div className="fa-empty-text">No evaluations yet</div>
        <div className="fa-empty-hint">
          Run <code>python -m scripts.auto_iterate --continuous</code> to start training
        </div>
      </div>
    )
  }

  const selected = entries[selectedIdx] ?? entries[entries.length - 1]
  const first = entries[0]
  const latest = entries[entries.length - 1]

  return (
    <div className="fa-training">
      {/* Progress bars — win rate per eval */}
      {entries.length > 1 && (
        <div className="fa-progress">
          <div className="fa-section-title">Progress Over Evaluations</div>
          <div className="fa-bars">
            {entries.map((e, i) => {
              const wr = e.metrics.win_rate * 100
              return (
                <div
                  key={i}
                  className={`fa-bar-row ${i === selectedIdx ? 'fa-bar-selected' : ''}`}
                  onClick={() => setSelectedIdx(i)}
                  title={`${e.label}: ${wr.toFixed(1)}% win rate`}
                >
                  <span className="fa-bar-label mono">{shortLabel(e.label)}</span>
                  <div className="fa-bar-track">
                    <div
                      className={`fa-bar-fill ${wr >= 50 ? 'bar-good' : wr >= 30 ? 'bar-mid' : 'bar-bad'}`}
                      style={{ width: `${Math.min(wr, 100)}%` }}
                    />
                  </div>
                  <span className="fa-bar-value mono">{wr.toFixed(1)}%</span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Detail grid for selected */}
      <div className="fa-detail">
        <div className="fa-detail-header">
          <span className="fa-detail-title">{selected.label}</span>
          <span className="fa-detail-time mono">{fmtTs(selected.timestamp)}</span>
        </div>

        {/* Nudge applied */}
        {selected.nudge && (
          <div className="fa-nudge-inline">
            <span className="fa-nudge-param mono">{selected.nudge.param}</span>
            <span className="fa-nudge-change">{selected.nudge.old_value} → {selected.nudge.new_value}</span>
            {selected.nudge.reverted && <span className="fa-badge-revert">REVERTED</span>}
          </div>
        )}

        <div className="fa-detail-grid">
          <DRow label="Win Rate" value={`${(selected.metrics.win_rate * 100).toFixed(1)}%`} />
          <DRow label="Take Rate" value={`${(selected.metrics.take_rate * 100).toFixed(1)}%`} />
          <DRow label="Profit Factor" value={selected.metrics.profit_factor.toFixed(2)} />
          <DRow label="Avg R" value={fmtR(selected.metrics.avg_r_multiple)} color={selected.metrics.avg_r_multiple >= 0 ? 'var(--green)' : 'var(--red)'} />
          <DRow label="Sharpe" value={fmtSharpe(selected.metrics.sharpe_ratio)} />
          <DRow label="Max DD" value={`${selected.metrics.max_drawdown.toFixed(1)}%`} color={selected.metrics.max_drawdown > 5 ? 'var(--red)' : undefined} />
          <DRow label="Reward" value={selected.metrics.mean_episode_reward.toFixed(3)} color={selected.metrics.mean_episode_reward >= 0 ? 'var(--green)' : 'var(--red)'} />
          <DRow label="Trades" value={String(selected.metrics.total_trades_taken)} />
          <DRow label="Signals" value={String(selected.metrics.total_signals_seen)} />
          <DRow label="Steps" value={selected.training_timesteps ? `${(selected.training_timesteps / 1000).toFixed(0)}K` : '—'} />
        </div>
      </div>

      {/* Comparison table */}
      {entries.length > 1 && (
        <div className="fa-comparison">
          <div className="fa-section-title">All Evaluations</div>
          <table className="fa-table">
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
                      {prev && <Arrow cur={m.win_rate} prev={prev.win_rate} />}
                    </td>
                    <td className="mono">{(m.take_rate * 100).toFixed(1)}</td>
                    <td className="mono">{m.profit_factor.toFixed(2)}</td>
                    <td className={`mono ${m.avg_r_multiple >= 0 ? 'positive' : 'negative'}`}>
                      {fmtR(m.avg_r_multiple)}
                      {prev && <Arrow cur={m.avg_r_multiple} prev={prev.avg_r_multiple} />}
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

/* ═══════════════════════════════════════════════════════════════════════
   FAILURES TAB
   ═══════════════════════════════════════════════════════════════════════ */

function FailuresTab({ entries }: { entries: TrainingEntry[] }) {
  // Show failures from the latest entry that has them
  const withFailures = entries.filter(e => e.failures?.failure_clusters?.length)
  const latest = withFailures.length > 0 ? withFailures[withFailures.length - 1] : null

  if (!latest || !latest.failures) {
    return (
      <div className="fa-empty">
        <div className="fa-empty-icon">📊</div>
        <div className="fa-empty-text">No failure analysis yet</div>
        <div className="fa-empty-hint">
          Run an evaluation with failure analysis enabled to see patterns
        </div>
      </div>
    )
  }

  const f = latest.failures
  const clusters = f.failure_clusters ?? []
  const exits = f.exit_reasons ?? {}

  return (
    <div className="fa-failures">
      {/* Summary strip */}
      <div className="fa-fail-summary">
        <div className="fa-fail-stat">
          <span className="fa-fail-stat-val mono">{f.losing_trades}</span>
          <span className="fa-fail-stat-label">Losses</span>
        </div>
        <div className="fa-fail-stat">
          <span className="fa-fail-stat-val mono">{f.winning_trades}</span>
          <span className="fa-fail-stat-label">Wins</span>
        </div>
        <div className="fa-fail-stat">
          <span className="fa-fail-stat-val mono">{f.total_trades}</span>
          <span className="fa-fail-stat-label">Total</span>
        </div>
        <div className="fa-fail-stat">
          <span className="fa-fail-stat-val mono">
            {f.total_trades > 0 ? `${((f.winning_trades / f.total_trades) * 100).toFixed(1)}%` : '—'}
          </span>
          <span className="fa-fail-stat-label">Accuracy</span>
        </div>
      </div>

      {/* Exit reasons */}
      <div className="fa-section-title">Exit Reasons</div>
      <div className="fa-exit-reasons">
        {Object.entries(exits)
          .sort((a, b) => b[1] - a[1])
          .map(([reason, count]) => (
            <div key={reason} className="fa-exit-chip">
              <span className="fa-exit-chip-label">{reason.replace(/_/g, ' ')}</span>
              <span className="fa-exit-chip-count mono">{count}</span>
            </div>
          ))}
      </div>

      {/* Failure clusters */}
      <div className="fa-section-title" style={{ marginTop: 12 }}>Failure Clusters</div>
      <div className="fa-clusters">
        {clusters.map((c, i) => (
          <ClusterCard key={i} cluster={c} totalLosses={f.losing_trades} />
        ))}
      </div>

      {/* From evaluation */}
      <div className="fa-fail-source mono">
        From: {latest.label} ({fmtTs(latest.timestamp)})
      </div>
    </div>
  )
}

function ClusterCard({ cluster, totalLosses }: { cluster: FailureCluster; totalLosses: number }) {
  const pct = totalLosses > 0 ? (cluster.count / totalLosses) * 100 : 0
  return (
    <div className="fa-cluster">
      <div className="fa-cluster-top">
        <span className="fa-cluster-name">{cluster.pattern.replace(/_/g, ' ')}</span>
        <span className="fa-cluster-pct mono">{pct.toFixed(0)}% of losses</span>
      </div>
      <div className="fa-cluster-bar">
        <div className="fa-cluster-fill" style={{ width: `${Math.min(cluster.impact * 100, 100)}%` }} />
      </div>
      <div className="fa-cluster-count mono">{cluster.count} trades</div>
      <div className="fa-cluster-suggestion">{cluster.suggestion}</div>
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   NUDGES TAB
   ═══════════════════════════════════════════════════════════════════════ */

function NudgesTab({ iterateState, entries }: { iterateState: IterateState | null; entries: TrainingEntry[] }) {
  const nudges = iterateState?.nudge_history ?? []
  const envConfig = iterateState?.env_config ?? {}
  const rewardConfig = iterateState?.reward_config ?? {}

  return (
    <div className="fa-nudges">
      {/* Current config snapshot */}
      <div className="fa-section-title">Current Configuration</div>
      <div className="fa-config-grid">
        {Object.entries(envConfig)
          .filter(([k]) => typeof envConfig[k] === 'number' && !['pip_value', 'initial_equity', 'episode_length_days', 'max_steps_per_episode', 'risk_per_trade_pct', 'atr_period', 'rsi_period', 'bb_period', 'bb_std'].includes(k))
          .map(([k, v]) => (
            <div key={k} className="fa-config-item">
              <span className="fa-config-key">{k.replace(/_/g, ' ')}</span>
              <span className="fa-config-val mono">{typeof v === 'number' ? (Number.isInteger(v) ? v : (v as number).toFixed(2)) : String(v)}</span>
            </div>
          ))}
        {Object.entries(rewardConfig)
          .filter(([k]) => ['correct_veto_reward', 'missed_winner_penalty', 'ideal_hold_max', 'dd_warning_threshold', 'dd_danger_threshold'].includes(k))
          .map(([k, v]) => (
            <div key={k} className="fa-config-item">
              <span className="fa-config-key">{k.replace(/_/g, ' ')}</span>
              <span className="fa-config-val mono">{typeof v === 'number' ? (Number.isInteger(v) ? v : (v as number).toFixed(2)) : String(v)}</span>
            </div>
          ))}
      </div>

      {/* Nudge history */}
      <div className="fa-section-title" style={{ marginTop: 12 }}>
        Nudge History
        {nudges.length > 0 && <span className="fa-count mono">{nudges.length} changes</span>}
      </div>
      {nudges.length === 0 ? (
        <div className="fa-empty-inline">No nudges applied yet</div>
      ) : (
        <div className="fa-nudge-list">
          {[...nudges].reverse().map((n, i) => (
            <div key={i} className={`fa-nudge-row ${n.reverted ? 'fa-nudge-reverted' : ''}`}>
              <span className="fa-nudge-iter mono">#{n.iteration}</span>
              <span className="fa-nudge-param mono">{n.param}</span>
              <span className="fa-nudge-vals mono">
                {n.old_value} → {n.new_value}
                <span className={n.direction > 0 ? 'positive' : 'negative'}>
                  {n.direction > 0 ? ' ▲' : ' ▼'}
                </span>
              </span>
              {n.reverted && <span className="fa-badge-revert">REVERTED</span>}
              <span className="fa-nudge-reason">{n.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════════════════════════════════════
   HELPERS
   ═══════════════════════════════════════════════════════════════════════ */

function MiniStat({ label, value, delta, unit, color, sub }: {
  label: string; value: string; delta?: number | null; unit?: string; color?: string; sub?: string
}) {
  const good = delta != null ? delta > 0 : undefined
  return (
    <div className="fa-ministat">
      <div className="fa-ministat-label">{label}</div>
      <div className="fa-ministat-value mono" style={color ? { color } : undefined}>{value}</div>
      {delta != null && (
        <div className={`fa-ministat-delta mono ${good ? 'positive' : 'negative'}`}>
          {delta >= 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(2)}{unit ?? ''}
        </div>
      )}
      {sub && <div className="fa-ministat-sub mono">{sub}</div>}
    </div>
  )
}

function DRow({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="fa-drow">
      <span className="fa-drow-label">{label}</span>
      <span className="fa-drow-value mono" style={color ? { color } : undefined}>{value}</span>
    </div>
  )
}

function Arrow({ cur, prev }: { cur: number; prev: number }) {
  if (Math.abs(cur - prev) < 0.0001) return null
  const up = cur > prev
  return <span className={`trend-arrow ${up ? 'trend-up' : 'trend-down'}`}>{up ? '▲' : '▼'}</span>
}

function shortLabel(label: string): string {
  if (label.length > 18) return label.substring(0, 16) + '…'
  return label
}

function fmtTs(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
  } catch { return iso.substring(0, 16) }
}

function fmtR(r: number): string {
  return `${r >= 0 ? '+' : ''}${r.toFixed(4)}`
}

function fmtSharpe(s: number): string {
  if (Math.abs(s) > 100000) return s > 0 ? '∞' : '-∞'
  return s.toFixed(2)
}
