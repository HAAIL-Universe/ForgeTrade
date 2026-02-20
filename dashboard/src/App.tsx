import { useState, useCallback, useRef, useEffect } from 'react'
import { api } from './api'
import { usePolling, useLocalStorage } from './hooks'
import { fmt$ } from './helpers'
import { Header, pickFirstActive } from './components/Header'
import MetricsRow from './components/MetricsRow'
import Card from './components/Card'
import CardContainer from './components/CardContainer'
import PositionsTable from './components/PositionsTable'
import TradeHistoryTable from './components/TradeHistoryTable'
import WatchlistTable from './components/WatchlistTable'
import SignalLogTable from './components/SignalLogTable'
import StreamsTable from './components/StreamsTable'
import StrategyInsight from './components/StrategyInsight'
import Controls from './components/Controls'
import Settings from './components/Settings'
import ForgeAgent from './components/ForgeAgent'
import Footer from './components/Footer'
import type {
  StatusResponse,
  PositionsResponse,
  PendingResponse,
  ClosedResponse,
  InsightResponse,
  SignalHistoryResponse,
  AccountResponse,
  TrainingHistoryResponse,
  IterateStatusResponse,
} from './types'

const POLL_MS = 5000
const CLOSED_POLL_MS = 5000  // match main poll interval for live updates

export default function App() {
  // ── Data polling ──
  const [statusData, , statusTs, refreshStatus] = usePolling<StatusResponse>(api.status, POLL_MS)
  const [posData] = usePolling<PositionsResponse>(api.positions, POLL_MS)
  const [pendingData] = usePolling<PendingResponse>(api.pending, POLL_MS)
  const [closedData] = usePolling<ClosedResponse>(api.closed, CLOSED_POLL_MS)
  const [insightData, , , refreshInsight] = usePolling<InsightResponse>(api.insight, POLL_MS)
  const [signalData] = usePolling<SignalHistoryResponse>(api.signalHistory, POLL_MS)
  const [accountData] = usePolling<AccountResponse>(api.account, POLL_MS)
  const [trainingData] = usePolling<TrainingHistoryResponse>(api.trainingHistory, 30000) // poll every 30s
  const [iterateData] = usePolling<IterateStatusResponse>(api.iterateStatus, 10000) // poll every 10s

  const handleSettingsSaved = useCallback(() => {
    // Force immediate refresh of status + insight after settings are applied
    refreshStatus()
    refreshInsight()
  }, [refreshStatus, refreshInsight])

  // ── Card collapse state ──
  const [collapsed, setCollapsed] = useLocalStorage<Record<string, boolean>>('ft_collapsed', {
    'card-signal-log': true,
    'card-settings': true,
    'card-training': true,
  })

  const toggleCard = useCallback((id: string) => {
    setCollapsed(prev => ({ ...prev, [id]: !prev[id] }))
  }, [setCollapsed])

  // ── Insight tab ──
  const [activeInsightTab, setActiveInsightTab] = useState<string | null>(null)

  // ── Derived data ──
  const streams = statusData?.streams ?? {}
  const primaryStream = pickFirstActive(streams)
  const mode = primaryStream?.mode ?? 'idle'
  const startedAt = primaryStream?.started_at ?? null
  const cbActive = primaryStream?.circuit_breaker_active ?? false
  const account = accountData?.account ?? null
  const positions = posData?.positions ?? []
  const closedTrades = closedData?.trades ?? []
  const totalPnl = closedData?.total_pnl ?? 0
  const signals = signalData?.signals ?? []
  const insights = insightData?.insights ?? {}
  const rlDecisions = insightData?.rl_decisions ?? []
  const trainingEntries = trainingData?.entries ?? []
  const iterateStatus = (iterateData?.status && 'phase' in iterateData.status ? iterateData.status : null) as import('./types').IterateStatus | null
  const iterateState = iterateData?.state ?? null

  // Find the ForgeAgent insight (the stream with RL actually enabled)
  const agentInsight = Object.values(insights).find(
    i => i.rl_mode != null && i.rl_mode !== 'disabled'
  ) ?? null

  // ── Signal log: "new since last viewed" counter ──
  const lastViewedCount = useRef(signals.length)
  const [newSignalCount, setNewSignalCount] = useState(0)

  useEffect(() => {
    if (!collapsed['card-signal-log']) {
      // Card is open — reset counter and snapshot current length
      lastViewedCount.current = signals.length
      setNewSignalCount(0)
    } else {
      // Card is collapsed — count new signals since last viewed
      const diff = signals.length - lastViewedCount.current
      setNewSignalCount(diff > 0 ? diff : 0)
    }
  }, [signals.length, collapsed])

  // Most recent signal for collapsed preview
  const latestSignal = signals.length > 0 ? signals[0] : null
  const signalPreview = latestSignal ? (
    <span className="signal-preview">
      <span className="mono">{latestSignal.evaluated_at?.substring(11, 19) ?? ''}</span>
      <span>{(latestSignal.pair ?? '').replace('_', '/')}</span>
      <span className={`badge badge-${latestSignal.status === 'skipped' ? 'skipped' : latestSignal.status === 'entered' ? 'entered' : latestSignal.status === 'halted' ? 'error' : 'no-signal'}`}>{latestSignal.status}</span>
      <span className="signal-preview-reason">{latestSignal.reason ?? ''}</span>
    </span>
  ) : null

  return (
    <>
      <Header mode={mode} startedAt={startedAt} circuitBreakerActive={cbActive} positions={positions} />
      <MetricsRow stream={primaryStream} account={account} positions={positions} agentInsight={agentInsight} rlDecisions={rlDecisions} />

      <CardContainer>
        <Card
          key="card-positions"
          id="card-positions"
          title="Open Positions"
          collapsed={!!collapsed['card-positions']}
          onToggle={toggleCard}
          badge={`${positions.length} open`}
        >
          <PositionsTable positions={positions} />
        </Card>

        <Card
          key="card-closed"
          id="card-closed"
          title="Trade History"
          collapsed={!!collapsed['card-closed']}
          onToggle={toggleCard}
          badge={<span className={pnlCls(totalPnl)}>Total: {fmt$(totalPnl)}</span>}
        >
          <TradeHistoryTable trades={closedTrades} />
        </Card>

        <Card
          key="card-watchlist"
          id="card-watchlist"
          title="Watchlist"
          collapsed={!!collapsed['card-watchlist']}
          onToggle={toggleCard}
        >
          <WatchlistTable signal={pendingData?.signal ?? null} />
        </Card>

        <Card
          key="card-signal-log"
          id="card-signal-log"
          title="Signal Log"
          collapsed={!!collapsed['card-signal-log']}
          onToggle={toggleCard}
          badge={newSignalCount > 0 ? String(newSignalCount) : undefined}
          collapsedContent={signalPreview}
        >
          <SignalLogTable signals={signals} />
        </Card>

        <Card
          key="card-insight"
          id="card-insight"
          title="Strategy Insight"
          collapsed={!!collapsed['card-insight']}
          onToggle={toggleCard}
          badge={insightLabel(insights, activeInsightTab)}
        >
          <StrategyInsight
            insights={insights}
            rlDecisions={rlDecisions}
            activeTab={activeInsightTab}
            onSelectTab={setActiveInsightTab}
          />
        </Card>

        <Card
          key="card-training"
          id="card-training"
          title="Forge Agent"
          collapsed={!!collapsed['card-training']}
          onToggle={toggleCard}
          badge={agentBadge(agentInsight, trainingEntries.length, iterateStatus)}
        >
          <ForgeAgent
            agentInsight={agentInsight}
            rlDecisions={rlDecisions}
            trainingEntries={trainingEntries}
            iterateStatus={iterateStatus}
            iterateState={iterateState}
          />
        </Card>

        <Card
          key="card-streams"
          id="card-streams"
          title="Streams"
          collapsed={!!collapsed['card-streams']}
          onToggle={toggleCard}
        >
          <StreamsTable
            streams={streams}
            activeTab={activeInsightTab}
            onSelectStream={setActiveInsightTab}
          />
        </Card>

        <Card
          key="card-controls"
          id="card-controls"
          title="Controls"
          collapsed={!!collapsed['card-controls']}
          onToggle={toggleCard}
        >
          <Controls />
        </Card>

        <Card
          key="card-settings"
          id="card-settings"
          title="Settings"
          collapsed={!!collapsed['card-settings']}
          onToggle={toggleCard}
        >
          <Settings onSaved={handleSettingsSaved} />
        </Card>
      </CardContainer>

      <Footer lastUpdated={statusTs} />
    </>
  )
}

function pnlCls(v: number | null): string {
  if (v == null) return 'neutral'
  return v >= 0 ? 'positive' : 'negative'
}

function insightLabel(insights: Record<string, { strategy?: string; pair?: string }>, tab: string | null): string {
  if (!tab || !insights[tab]) return '—'
  const ins = insights[tab]
  const strat = (ins.strategy ?? '—').toUpperCase()
  const pair = ins.pair ? ins.pair.replace('_', '/') : ''
  return `${strat} · ${pair}`
}

function agentBadge(
  insight: { rl_mode?: string } | null,
  entryCount: number,
  iterate: { phase?: string } | null,
): string | undefined {
  const parts: string[] = []
  const mode = insight?.rl_mode
  if (mode === 'active') parts.push('ACTIVE')
  else if (mode === 'shadow') parts.push('SHADOW')

  const phase = iterate?.phase
  if (phase && phase !== 'idle') parts.push(phase.toUpperCase())
  else if (entryCount > 0) parts.push(`${entryCount} evals`)

  return parts.length > 0 ? parts.join(' · ') : undefined
}
