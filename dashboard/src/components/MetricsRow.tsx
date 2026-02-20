import { fmt$, fmtPct, pnlClass } from '../helpers'
import type { StreamStatus, AccountData, Position, StreamInsight, RLDecision } from '../types'

interface Props {
  stream: StreamStatus | null
  account: AccountData | null
  positions: Position[]
  agentInsight?: StreamInsight | null
  rlDecisions?: RLDecision[]
}

export default function MetricsRow({ stream, account, positions, agentInsight, rlDecisions = [] }: Props) {
  const eq = account?.equity ?? stream?.equity ?? null
  const bal = account?.balance ?? stream?.balance ?? null
  const upnl = account?.unrealized_pnl ?? (eq != null && bal != null ? eq - bal : null)
  const dd = account?.drawdown_pct ?? stream?.drawdown_pct ?? null
  const ddVal = dd != null ? parseFloat(String(dd)) : 0
  const ddBarWidth = Math.min(ddVal * 10, 100) + '%'
  const ddBarClass = 'dd-bar ' + (ddVal < 5 ? 'dd-yellow' : ddVal < 8 ? 'dd-orange' : 'dd-red')

  const hasPositions = positions.length > 0

  return (
    <div className="metrics">
      <div className="metric">
        <div className="metric-label">Equity</div>
        <div className="metric-value mono">{fmt$(eq)}</div>
        {upnl != null && (
          <div className={`metric-sub mono ${pnlClass(upnl)}`}>
            {upnl >= 0 ? '+' : ''}{fmt$(upnl)}
          </div>
        )}
      </div>
      <div className="metric">
        <div className="metric-label">Unrealised P&L</div>
        {hasPositions ? (
          <div className="upnl-positions">
            {positions.map((p, i) => {
              const pnl = p.unrealized_pnl ?? 0
              return (
                <div key={i} className="upnl-entry">
                  <div className="upnl-pair">{(p.instrument ?? '—').replace('_', '/')}</div>
                  <div className={`upnl-value mono ${pnlClass(pnl)}`}>
                    {pnl >= 0 ? '+' : ''}{fmt$(pnl)}
                  </div>
                </div>
              )
            })}
          </div>
        ) : (
          <div className={`metric-value mono ${pnlClass(upnl)}`}>
            {upnl != null ? `${upnl >= 0 ? '+' : ''}${fmt$(upnl)}` : '—'}
          </div>
        )}
      </div>
      <AgentMetricCard insight={agentInsight ?? null} dd={dd} ddBarWidth={ddBarWidth} ddBarClass={ddBarClass} decisions={rlDecisions} />
    </div>
  )
}

/* ── ForgeAgent Metric Card ── */
function AgentMetricCard({
  insight,
  dd,
  ddBarWidth,
  ddBarClass,
  decisions,
}: {
  insight: StreamInsight | null
  dd: number | null
  ddBarWidth: string
  ddBarClass: string
  decisions: RLDecision[]
}) {
  const mode = insight?.rl_mode ?? 'disabled'
  const decision = insight?.rl_filter ?? null
  const conf = insight?.rl_confidence
  const confPct = conf !== undefined ? Math.round(conf * 100) : null

  const modeLabel = mode === 'active' ? 'ACTIVE' : mode === 'shadow' ? 'SHADOW' : 'OFF'
  const modeDot = mode === 'active' ? 'agent-dot-active' : mode === 'shadow' ? 'agent-dot-shadow' : 'agent-dot-off'

  const takes = decisions.filter(d => d.action === 'TAKE').length
  const vetos = decisions.filter(d => d.action === 'VETO').length
  const total = decisions.length
  const latest = decisions.length > 0 ? decisions[decisions.length - 1] : null

  let decisionText = 'Idle'
  let decisionColor = 'var(--text-muted)'
  if (latest) {
    decisionText = latest.action === 'TAKE' ? 'TAKE' : 'VETO'
    decisionColor = latest.action === 'TAKE' ? 'var(--green)' : 'var(--red)'
  } else if (mode === 'disabled') {
    decisionText = 'Not trained'
  }

  return (
    <div className="metric agent-metric">
      <div className="metric-label">
        <span className={`agent-dot ${modeDot}`} />
        ForgeAgent
      </div>
      <div className="agent-metric-body">
        <div className="agent-metric-mode">
          <span className="agent-mode-tag mono">{modeLabel}</span>
        </div>
        <div className="agent-metric-decision">
          {latest ? (
            <>
              <span className="agent-metric-icon" style={{ color: decisionColor }}>
                {latest.action === 'TAKE' ? '✓' : '✗'}
              </span>
              <span className="agent-metric-text mono" style={{ color: decisionColor }}>
                {decisionText}
              </span>
              {confPct !== null && (
                <span className="agent-metric-conf mono" style={{ color: confPct >= 70 ? 'var(--green)' : confPct >= 55 ? 'var(--yellow)' : 'var(--red)' }}>
                  {confPct}%
                </span>
              )}
            </>
          ) : (
            <span className="agent-metric-text mono" style={{ color: decisionColor }}>{decisionText}</span>
          )}
        </div>
        {total > 0 && (
          <div className="agent-metric-tally mono">
            {total} assessed · <span style={{ color: 'var(--green)' }}>{takes} take</span> · <span style={{ color: 'var(--red)' }}>{vetos} veto</span>
          </div>
        )}
        {confPct !== null && (
          <div className="agent-conf-bar" style={{ marginTop: 6 }}>
            <div
              className={`agent-conf-fill ${confPct >= 70 ? 'agent-conf-fill-high' : confPct >= 55 ? 'agent-conf-fill-mid' : 'agent-conf-fill-low'}`}
              style={{ width: `${confPct}%` }}
            />
          </div>
        )}
      </div>
      {/* Compact drawdown line */}
      <div className="agent-dd-row">
        <span className="agent-dd-label">DD</span>
        <span className="agent-dd-value mono">{fmtPct(dd)}</span>
        <div className="dd-bar-container" style={{ flex: 1 }}>
          <div className={ddBarClass} style={{ width: ddBarWidth }} />
        </div>
      </div>
    </div>
  )
}
