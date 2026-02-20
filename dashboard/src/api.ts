import type {
  StatusResponse,
  PositionsResponse,
  PendingResponse,
  ClosedResponse,
  InsightResponse,
  SignalHistoryResponse,
  AccountResponse,
  SettingsData,
  StreamSettingsResponse,
  StreamSettingsEntry,
  TrainingHistoryResponse,
  IterateStatusResponse,
} from './types'

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json()
}

export const api = {
  status: () => fetchJSON<StatusResponse>('/status'),
  positions: () => fetchJSON<PositionsResponse>('/positions'),
  pending: () => fetchJSON<PendingResponse>('/signals/pending'),
  closed: () => fetchJSON<ClosedResponse>('/trades/closed?limit=50'),
  insight: () => fetchJSON<InsightResponse>('/strategy/insight'),
  signalHistory: () => fetchJSON<SignalHistoryResponse>('/signals/history'),
  account: () => fetchJSON<AccountResponse>('/account'),
  settings: () => fetchJSON<SettingsData>('/settings'),
  streamSettings: () => fetchJSON<StreamSettingsResponse>('/stream-settings'),
  trainingHistory: () => fetchJSON<TrainingHistoryResponse>('/agent/training-history'),
  iterateStatus: () => fetchJSON<IterateStatusResponse>('/agent/iterate-status'),

  saveSettings: async (data: SettingsData) => {
    const r = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  saveStreamSettings: async (streams: Partial<StreamSettingsEntry>[]) => {
    const r = await fetch('/stream-settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ streams }),
    })
    if (!r.ok) throw new Error(`HTTP ${r.status}`)
    return r.json()
  },

  pauseAll: () => fetch('/control/pause', { method: 'POST' }),
  resumeAll: () => fetch('/control/resume', { method: 'POST' }),
  emergencyStop: () => fetch('/control/emergency-stop', { method: 'POST' }),

  pauseStream: (name: string) =>
    fetch(`/control/stream/${encodeURIComponent(name)}/pause`, { method: 'POST' }),
  resumeStream: (name: string) =>
    fetch(`/control/stream/${encodeURIComponent(name)}/resume`, { method: 'POST' }),
}
