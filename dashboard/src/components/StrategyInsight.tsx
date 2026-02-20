import { useState, useEffect } from 'react'
import { instrumentLabel } from '../helpers'
import type { StreamInsight, RLDecision } from '../types'

interface Props {
  insights: Record<string, StreamInsight>
  rlDecisions?: RLDecision[]
  activeTab: string | null
  onSelectTab: (name: string) => void
}

export default function StrategyInsight({ insights, rlDecisions = [], activeTab, onSelectTab }: Props) {
  const keys = Object.keys(insights)

  // Auto-select first tab
  useEffect(() => {
    if (keys.length && (!activeTab || !keys.includes(activeTab))) {
      onSelectTab(keys[0])
    }
  }, [keys, activeTab, onSelectTab])

  if (!keys.length) {
    return <div style={{ color: 'var(--text-muted)', padding: 16 }}>Waiting for data...</div>
  }

  const ins = activeTab ? insights[activeTab] : null

  return (
    <>
      {/* Stream tabs */}
      <div className="stream-tabs">
        {keys.map(sn => {
          const isScalp = sn.includes('scalp')
          const dotClass = isScalp ? 'tab-dot-scalp' : 'tab-dot-swing'
          const pair = insights[sn].pair ?? ''
          const label = instrumentLabel(pair) || sn
          return (
            <div
              key={sn}
              className={`stream-tab${activeTab === sn ? ' active' : ''}`}
              onClick={() => onSelectTab(sn)}
            >
              <span className={`tab-dot ${dotClass}`} />
              {label}
            </div>
          )
        })}
      </div>

      {ins && <InsightBody ins={ins} rlDecisions={rlDecisions} />}
    </>
  )
}

/* ── Insight Body ── */
function InsightBody({ ins, rlDecisions }: { ins: StreamInsight; rlDecisions: RLDecision[] }) {
  const checks = ins.checks ?? {}
  const isScalp = (ins.strategy ?? '').toLowerCase().includes('scalp')

  // Readiness
  const checkKeys = Object.keys(checks)
  const passed = checkKeys.filter(k => checks[k] === true).length
  const pct = checkKeys.length > 0 ? Math.round((passed / checkKeys.length) * 100) : 0
  const pctClass = pct >= 100 ? 'check-pass' : pct >= 50 ? 'check-wait' : 'check-fail'

  return (
    <>
      {/* Readiness */}
      <div style={{ padding: '0 4px 8px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <span className="metric-label" style={{ margin: 0 }}>Entry Readiness</span>
          <span className={`readiness-pct mono ${pctClass}`}>{pct}%</span>
        </div>
        <div className="readiness-bar-container">
          <div className="readiness-bar" style={{ width: `${pct}%` }} />
        </div>
      </div>

      {/* Checklist + Details */}
      <div className="insight-grid">
        <div>
          {isScalp ? <ScalpChecklist ins={ins} checks={checks} /> : <SwingChecklist ins={ins} checks={checks} />}
        </div>
        <div>
          {isScalp ? <ScalpDetails ins={ins} rlDecisions={rlDecisions} /> : <SwingDetails ins={ins} />}
        </div>
      </div>
    </>
  )
}

/* ── Check Item ── */
function CheckItem({ pass, label, detail }: { pass: boolean | null; label: string; detail: string }) {
  const icon = pass === true ? '✓' : pass === false ? '✗' : '◯'
  const iconCls = pass === true ? 'check-pass' : pass === false ? 'check-fail' : 'check-wait'
  return (
    <div className="check-item">
      <span className={`check-icon ${iconCls}`}>{icon}</span>
      <span className="check-label">{label}</span>
      <span className="check-detail mono">{detail}</span>
    </div>
  )
}

/* ── Swing Checklist (SR Rejection) ── */
function SwingChecklist({ ins, checks }: { ins: StreamInsight; checks: Record<string, boolean> }) {
  const zoneDetail = ins.zones
    ? `${ins.zones.total} zones (${ins.zones.support.length}S / ${ins.zones.resistance.length}R)`
    : '—'

  let proxDetail = '—'
  if (ins.nearest_zone) proxDetail = `${ins.nearest_zone.distance_pips} pips to ${ins.nearest_zone.type}`

  let wickDetail = '—'
  if (ins.latest_h4) {
    const parts: string[] = []
    if (ins.latest_h4.buy_rejection_wick) parts.push('Bull wick ✓')
    if (ins.latest_h4.sell_rejection_wick) parts.push('Bear wick ✓')
    if (!parts.length) parts.push('No rejection')
    parts.push(ins.latest_h4.zones_touched > 0 ? `${ins.latest_h4.zones_touched} zone(s) touched` : 'No zone touch')
    wickDetail = parts.join(' · ')
  }

  let riskDetail = '—'
  if (ins.signal) {
    riskDetail = `${ins.signal.direction.toUpperCase()} @ ${ins.signal.entry} SL:${ins.signal.sl} TP:${ins.signal.tp}`
  }

  // H4 Trend alignment detail
  let trendAlignDetail = '—'
  if (ins.trend) {
    const dir = ins.trend.direction
    const potDir = (ins as any).potential_direction as string | undefined
    if (dir === 'flat') {
      trendAlignDetail = 'Flat — both directions allowed'
    } else if (!potDir) {
      trendAlignDetail = `H4 ${dir} (no signal to filter)`
    } else if (checks.trend_aligned === false) {
      trendAlignDetail = `H4 ${dir} — blocks ${potDir.toUpperCase()}`
    } else {
      trendAlignDetail = `H4 ${dir} — ${potDir.toUpperCase()} aligned`
    }
  }

  return (
    <>
      <CheckItem pass={checks.circuit_breaker_clear ?? null} label="Circuit Breaker" detail={checks.circuit_breaker_clear ? 'Clear' : 'ACTIVE — trading halted'} />
      <CheckItem pass={checks.in_session ?? null} label="Session Window" detail={checks.in_session ? 'In session' : 'Outside hours'} />
      <CheckItem pass={checks.zones_detected ?? null} label="S/R Zones" detail={zoneDetail} />
      <CheckItem pass={checks.zone_proximity ?? null} label="Zone Proximity" detail={proxDetail} />
      <CheckItem pass={checks.rejection_wick ?? null} label="Rejection Wick" detail={wickDetail} />
      <CheckItem pass={checks.trend_aligned ?? null} label="H4 Trend" detail={trendAlignDetail} />
      <CheckItem pass={checks.risk_calculated ?? null} label="Risk / SL+TP" detail={riskDetail} />
    </>
  )
}

/* ── Swing Details (SR Rejection) ── */
function SwingDetails({ ins }: { ins: StreamInsight }) {
  return (
    <>
      {/* Zone Map */}
      <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Zone Map
      </div>
      <div style={{ minHeight: 28 }}>
        {ins.zones && (ins.zones.support.length > 0 || ins.zones.resistance.length > 0) ? (
          <>
            {ins.zones.support.map((sz, i) => {
              const isNearest = ins.nearest_zone && Math.abs(sz.price - ins.nearest_zone.price) < 0.00001
              return <span key={`s${i}`} className={`zone-chip zone-support ${isNearest ? 'zone-nearest' : ''}`}>S {sz.price.toFixed(5)} ({sz.touches})</span>
            })}
            {ins.zones.resistance.map((rz, i) => {
              const isNearest = ins.nearest_zone && Math.abs(rz.price - ins.nearest_zone.price) < 0.00001
              return <span key={`r${i}`} className={`zone-chip zone-resistance ${isNearest ? 'zone-nearest' : ''}`}>R {rz.price.toFixed(5)} ({rz.touches})</span>
            })}
          </>
        ) : 'No zones'}
      </div>

      {/* Nearest Zone */}
      <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Nearest Zone
      </div>
      {ins.nearest_zone ? (
        <>
          <Stat label="Level" value={ins.nearest_zone.price.toFixed(5)} />
          <Stat label="Type" value={ins.nearest_zone.type.toUpperCase()} />
          <Stat label="Distance" value={`${ins.nearest_zone.distance_pips} pips`} />
          {(() => {
            const proxPct = Math.max(0, Math.min(100, (1 - ins.nearest_zone!.distance_pips / 50) * 100))
            const proxClass = proxPct > 60 ? 'prox-close' : proxPct > 30 ? 'prox-mid' : 'prox-far'
            return (
              <div className="proximity-bar-container">
                <div className={`proximity-bar ${proxClass}`} style={{ width: `${proxPct}%` }} />
              </div>
            )
          })()}
        </>
      ) : (
        <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No zones detected</div>
      )}

      {/* Stats */}
      <div style={{ marginTop: 12 }}>
        <Stat label="Price" value={ins.current_price?.toFixed(5) ?? '—'} />
        <Stat label="ATR (Daily)" value={ins.atr?.toFixed(5) ?? '—'} />
        {ins.latest_h4 && (
          <Stat
            label="Last H4"
            value={`O:${ins.latest_h4.open.toFixed(5)} H:${ins.latest_h4.high.toFixed(5)} L:${ins.latest_h4.low.toFixed(5)} C:${ins.latest_h4.close.toFixed(5)}`}
          />
        )}
      </div>
    </>
  )
}

/* ── Agent Check Item ── */
function AgentCheckItem({ ins }: { ins: StreamInsight }) {
  const mode = ins.rl_mode ?? 'disabled'

  const decision = ins.rl_filter
  const conf = ins.rl_confidence

  let detail: string
  let pass: boolean | null

  if (mode === 'disabled') {
    detail = 'Not trained'
    pass = null
  } else if (decision === 'approved' && conf !== undefined) {
    detail = `TAKE (${(conf * 100).toFixed(0)}%)`
    pass = true
  } else if (decision === 'vetoed' && conf !== undefined) {
    detail = `VETO (${(conf * 100).toFixed(0)}%)`
    pass = false
  } else if (mode === 'active') {
    detail = 'Awaiting signal'
    pass = null
  } else {
    detail = 'Observing'
    pass = null
  }

  return <CheckItem pass={pass} label="ForgeAgent" detail={detail} />
}

/* ── Scalp Checklist ── */
function ScalpChecklist({ ins, checks }: { ins: StreamInsight; checks: Record<string, boolean> }) {
  let trendDetail = '—'
  if (ins.trend) trendDetail = `${ins.trend.direction.toUpperCase()} (slope: ${ins.trend.slope})`

  let spreadDetail = '—'
  if (ins.spread_pips !== undefined) spreadDetail = `${ins.spread_pips} pips (max ${ins.max_spread_pips ?? 4})`

  let pullDetail = '—'
  if (ins.ema9 !== undefined) pullDetail = `EMA(9): ${ins.ema9} / Δ: ${ins.price_vs_ema}`

  let confDetail = '—'
  if (ins.signal) confDetail = ins.signal.reason
  else if (ins.result === 'no_confirmation_pattern') confDetail = 'No pattern found'

  let slDetail = '—'
  if (ins.sl !== undefined) slDetail = ins.sl.toFixed(2)
  else if (ins.result === 'sl_out_of_bounds') slDetail = 'SL outside bounds'

  let riskDetail = '—'
  if (ins.signal && ins.sl !== undefined && ins.tp !== undefined) {
    riskDetail = `${ins.signal.direction.toUpperCase()} @ ${ins.signal.entry_price.toFixed(2)} SL:${ins.sl.toFixed(2)} TP:${ins.tp.toFixed(2)}`
  }

  return (
    <>
      <CheckItem pass={checks.circuit_breaker_clear ?? null} label="Circuit Breaker" detail={checks.circuit_breaker_clear ? 'Clear' : 'ACTIVE — trading halted'} />
      <CheckItem pass={checks.in_session ?? null} label="Session Window" detail={checks.in_session ? 'In session' : 'Outside hours'} />
      <CheckItem pass={checks.trend_detected ?? null} label="Bias (M1)" detail={trendDetail} />
      <CheckItem pass={checks.spread_acceptable ?? null} label="Spread Filter" detail={spreadDetail} />
      <CheckItem pass={checks.pullback_to_ema ?? null} label="EMA Pullback" detail={pullDetail} />
      <CheckItem pass={checks.confirmation_pattern ?? null} label="Candle Pattern" detail={confDetail} />
      <CheckItem pass={checks.sl_valid ?? null} label="SL Valid" detail={slDetail} />
      <CheckItem pass={checks.risk_calculated ?? null} label="Risk / SL+TP" detail={riskDetail} />
      <AgentCheckItem ins={ins} />
    </>
  )
}

/* ── Scalp Details ── */
function ScalpDetails({ ins, rlDecisions }: { ins: StreamInsight; rlDecisions: RLDecision[] }) {
  const [tfExpanded, setTfExpanded] = useState(false)
  const [tfCycleIdx, setTfCycleIdx] = useState(0)
  const tfOrder = ['S5', 'M1', 'M5', 'M15', 'M30', 'H1']
  const mtf = ins.multi_tf_trends ?? {}

  // Cycle timeframes
  useEffect(() => {
    if (tfExpanded) return
    const id = setInterval(() => setTfCycleIdx(prev => (prev + 1) % tfOrder.length), 3000)
    return () => clearInterval(id)
  }, [tfExpanded, tfOrder.length])

  return (
    <>
      <div style={{ color: 'var(--text-secondary)', fontSize: 12, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Trend Analysis
      </div>

      {tfOrder.map((tf, i) => {
        const tfd = mtf[tf] ?? {}
        const dir = tfd.direction ?? 'unknown'
        const cls = dir === 'bullish' ? 'tf-bullish' : dir === 'bearish' ? 'tf-bearish' : dir === 'flat' ? 'tf-flat' : 'tf-unknown'
        const arrow = dir === 'bullish' ? '▲' : dir === 'bearish' ? '▼' : dir === 'flat' ? '▬' : '?'
        const visible = tfExpanded || i === (tfCycleIdx % tfOrder.length)
        if (!visible) return null

        return (
          <div key={tf} className="tf-trend-row" onClick={() => setTfExpanded(!tfExpanded)}>
            <span className="tf-trend-label mono">{tf}</span>
            <span className={`tf-trend-dir mono ${cls}`}>{arrow} {dir.toUpperCase()}</span>
          </div>
        )
      })}

      {/* Bias values */}
      {ins.trend && (
        <div style={{ marginTop: 8, paddingTop: 6, borderTop: '1px solid var(--border-subtle)' }}>
          <Stat label="Bias: latest" value={String(ins.trend.ema_fast)} />
          <Stat label="Bias: window start" value={String(ins.trend.ema_slow)} />
        </div>
      )}

      {/* Latest candle */}
      <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>
        Latest M1 Candle
      </div>
      {ins.latest_candle ? (
        <>
          <Stat label="Price" value={ins.latest_candle.close.toFixed(2)} />
          <Stat label="OHLC" value={`O:${ins.latest_candle.open.toFixed(2)} H:${ins.latest_candle.high.toFixed(2)} L:${ins.latest_candle.low.toFixed(2)}`} />
        </>
      ) : <div style={{ color: 'var(--text-muted)' }}>—</div>}

      {/* Signal */}
      {ins.signal && (
        <>
          <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: 12, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.5px' }}>Signal</div>
          <Stat label="Direction" value={ins.signal.direction.toUpperCase()} color={ins.signal.direction === 'buy' ? 'var(--green)' : 'var(--red)'} />
          <Stat label="Entry" value={ins.signal.entry_price.toFixed(2)} />
          {ins.sl !== undefined && <Stat label="SL" value={ins.sl.toFixed(2)} />}
          {ins.tp !== undefined && <Stat label="TP" value={ins.tp.toFixed(2)} />}
          {ins.rr_ratio && <Stat label="R:R" value={`1:${ins.rr_ratio}`} />}
        </>
      )}

      {/* Spread */}
      {ins.spread_pips !== undefined && (
        <div style={{ marginTop: 12 }}>
          <Stat label="Est. Spread" value={`${ins.spread_pips} pips`} />
        </div>
      )}

      {/* ForgeAgent Decision Card */}
      <AgentDecisionCard ins={ins} decisions={rlDecisions} />
    </>
  )
}

/* ── ForgeAgent Decision Card ── */
function AgentDecisionCard({ ins, decisions }: { ins: StreamInsight; decisions: RLDecision[] }) {
  const mode = ins.rl_mode ?? 'disabled'

  const badgeClass = mode === 'active' ? 'agent-badge-active'
    : mode === 'shadow' ? 'agent-badge-shadow'
    : 'agent-badge-disabled'

  const decision = ins.rl_filter
  const conf = ins.rl_confidence
  const assessedAt = ins.rl_assessed_at

  const confPct = conf !== undefined ? Math.round(conf * 100) : null
  const confClass = confPct !== null
    ? confPct >= 75 ? 'agent-conf-fill-high' : confPct >= 55 ? 'agent-conf-fill-mid' : 'agent-conf-fill-low'
    : ''

  const timeAgo = assessedAt ? formatTimeAgo(assessedAt) : null

  return (
    <div className="agent-card">
      <div className="agent-card-header">
        <span className="agent-card-title">ForgeAgent</span>
        <span className={`agent-badge ${badgeClass}`}>
          {mode === 'active' ? '● ACTIVE' : mode === 'shadow' ? '◐ SHADOW' : '○ OFF'}
        </span>
      </div>

      {decision ? (
        <>
          <div className="agent-decision">
            <span className={`agent-decision-icon ${decision === 'approved' ? 'agent-decision-take' : 'agent-decision-veto'}`}>
              {decision === 'approved' ? '✓' : '✗'}
            </span>
            <span style={{ fontWeight: 700, fontSize: 13, color: decision === 'approved' ? 'var(--green)' : 'var(--red)' }}>
              {decision === 'approved' ? 'TAKE' : 'VETO'}
            </span>
            {confPct !== null && (
              <>
                <div className="agent-conf-bar">
                  <div className={`agent-conf-fill ${confClass}`} style={{ width: `${confPct}%` }} />
                </div>
                <span className={`agent-conf-label`} style={{ color: confPct >= 75 ? 'var(--green)' : confPct >= 55 ? 'var(--yellow)' : 'var(--red)' }}>
                  {confPct}%
                </span>
              </>
            )}
          </div>
          {timeAgo && <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 4 }}>{timeAgo}</div>}
        </>
      ) : (
        <div className="agent-idle">
          {mode === 'shadow' ? 'Observing — no signal assessed yet'
           : mode === 'active' ? 'Awaiting signal…'
           : 'Train the agent to activate'}
        </div>
      )}

      {/* Decision log */}
      {decisions.length > 0 && (
        <div className="agent-log">
          <div className="agent-log-header">
            <span className="agent-log-title">Recent Assessments</span>
            <span className="agent-log-count mono">{decisions.length}</span>
          </div>
          {[...decisions].reverse().map((d, i) => (
            <div key={i} className="agent-log-entry">
              <span className="agent-log-time mono">{d.timestamp.substring(11, 19)}</span>
              <span className={`agent-log-action ${d.action === 'TAKE' ? 'agent-log-take' : 'agent-log-veto'}`}>
                {d.action === 'TAKE' ? '✓' : '✗'} {d.action}
              </span>
              <span className="agent-log-dir mono">{d.direction}</span>
              <span className="agent-log-price mono">{d.entry_price}</span>
              <span className="agent-log-conf mono" style={{ color: d.confidence >= 0.7 ? 'var(--green)' : d.confidence >= 0.55 ? 'var(--yellow)' : 'var(--red)' }}>
                {Math.round(d.confidence * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Format ISO timestamp as relative time (e.g. "12s ago", "3m ago") */
function formatTimeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 0) return 'just now'
  const secs = Math.floor(diff / 1000)
  if (secs < 60) return `${secs}s ago`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  return `${hrs}h ago`
}

/* ── Shared stat row ── */
function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="insight-stat">
      <span className="insight-stat-label">{label}</span>
      <span className="insight-stat-value mono" style={color ? { color } : undefined}>{value}</span>
    </div>
  )
}
