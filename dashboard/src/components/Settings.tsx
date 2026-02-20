import { useState, useEffect } from 'react'
import { api } from '../api'
import type { SettingsData, StreamSettingsEntry } from '../types'

interface SettingsProps {
  onSaved?: () => void
}

export default function Settings({ onSaved }: SettingsProps) {
  const [settings, setSettings] = useState<SettingsData>({
    max_drawdown_pct: 10.0,
    max_concurrent_positions: 1,
    poll_interval_seconds: 300,
    leverage: 30,
  })
  const [streams, setStreams] = useState<StreamSettingsEntry[]>([])
  const [status, setStatus] = useState<{ text: string; color: string }>({ text: '', color: '' })

  useEffect(() => {
    api.settings().then(setSettings).catch(() => {})
    api.streamSettings().then(r => setStreams(r.streams)).catch(() => {})
  }, [])

  const update = (key: keyof SettingsData, value: string) => {
    setSettings(prev => ({ ...prev, [key]: parseFloat(value) || 0 }))
  }

  const updateStream = (idx: number, key: 'risk_per_trade_pct' | 'rr_ratio' | 'session_start_utc' | 'session_end_utc', value: string) => {
    setStreams(prev => prev.map((s, i) =>
      i === idx ? { ...s, [key]: parseFloat(value) || 0 } : s
    ))
  }

  const handleSave = async () => {
    setStatus({ text: 'Saving...', color: 'var(--yellow)' })
    try {
      const [globalRes, streamRes] = await Promise.all([
        api.saveSettings(settings),
        api.saveStreamSettings(
          streams.map(s => ({
            name: s.name,
            risk_per_trade_pct: s.risk_per_trade_pct,
            rr_ratio: s.rr_ratio,
            session_start_utc: s.session_start_utc,
            session_end_utc: s.session_end_utc,
          }))
        ),
      ])
      // Check response bodies for backend validation errors
      const errors: string[] = []
      if (globalRes?.status === 'error') errors.push(...(globalRes.errors ?? ['Global settings rejected']))
      if (streamRes?.status === 'error') errors.push(...(streamRes.errors ?? ['Stream settings rejected']))
      if (errors.length > 0) {
        setStatus({ text: `✗ ${errors.join('; ')}`, color: 'var(--red)' })
        return
      }
      setStatus({ text: '✓ Applied', color: 'var(--green)' })
      // Trigger immediate dashboard refresh so insight/status reflect new settings
      onSaved?.()
      setTimeout(() => setStatus({ text: '', color: '' }), 3000)
    } catch (e) {
      setStatus({ text: `✗ Error: ${(e as Error).message}`, color: 'var(--red)' })
    }
  }

  const fmtPair = (inst: string) => inst.replace('_', '/')

  return (
    <>
      {/* Per-stream settings */}
      <div className="stream-settings-label">Per-Stream Settings</div>
      <div className="table-scroll">
      <table className="stream-settings-table">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Strategy</th>
            <th>Risk %</th>
            <th>R:R</th>
            <th>Session</th>
          </tr>
        </thead>
        <tbody>
          {streams.map((s, i) => (
            <tr key={s.name}>
              <td className="mono">{fmtPair(s.instrument)}</td>
              <td className="stream-strat-badge">{s.strategy === 'sr_rejection' ? 'SR' : s.strategy === 'trend_scalp' ? 'Scalp' : 'MR'}</td>
              <td>
                <input className="stream-input mono" type="number" step={0.1} min={0.1} max={5.0}
                  value={s.risk_per_trade_pct} onChange={e => updateStream(i, 'risk_per_trade_pct', e.target.value)} />
              </td>
              <td>
                {s.strategy === 'mean_reversion' ? (
                  <span className="stream-rr-na">BB mid</span>
                ) : (
                  <input className="stream-input mono" type="number" step={0.1} min={0.5} max={10.0}
                    value={s.rr_ratio ?? 2.0} onChange={e => updateStream(i, 'rr_ratio', e.target.value)} />
                )}
              </td>
              <td className="session-range">
                <input className="stream-input mono session-input" type="number" step={1} min={0} max={23}
                  value={s.session_start_utc} onChange={e => updateStream(i, 'session_start_utc', e.target.value)} />
                <span className="session-dash">–</span>
                <input className="stream-input mono session-input" type="number" step={1} min={0} max={24}
                  value={s.session_end_utc} onChange={e => updateStream(i, 'session_end_utc', e.target.value)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>

      {/* Global settings */}
      <div className="stream-settings-label" style={{ marginTop: 16 }}>Global Settings</div>
      <SettingsRow label="Max Drawdown" value={settings.max_drawdown_pct} unit="%" hint="Circuit breaker threshold"
        onChange={v => update('max_drawdown_pct', v)} step={0.5} min={1.0} max={25.0} />

      <SettingsRow label="Max Concurrent Positions" value={settings.max_concurrent_positions} unit="" hint="Per instrument"
        onChange={v => update('max_concurrent_positions', v)} step={1} min={1} max={10} />
      <SettingsRow label="Poll Interval" value={settings.poll_interval_seconds} unit="sec" hint="10 – 3600s"
        onChange={v => update('poll_interval_seconds', v)} step={10} min={10} max={3600} />
      <SettingsRow label="Leverage" value={settings.leverage} unit=":1" hint="Set by OANDA / your jurisdiction"
        onChange={v => update('leverage', v)} step={1} min={1} max={500} />
      <div style={{ display: 'flex', gap: 10, marginTop: 12, alignItems: 'center' }}>
        <button className="btn-save" onClick={handleSave}>Save Settings</button>
        {status.text && <span className="mono" style={{ fontSize: 12, color: status.color }}>{status.text}</span>}
      </div>
    </>
  )
}

function SettingsRow({ label, value, unit, hint, onChange, step, min, max }: {
  label: string; value: number; unit: string; hint: string
  onChange: (v: string) => void; step: number; min: number; max: number
}) {
  return (
    <div className="settings-row">
      <span className="settings-label">{label}</span>
      <input className="settings-input mono" type="number" step={step} min={min} max={max}
        value={value} onChange={e => onChange(e.target.value)} />
      <span className="settings-unit">{unit}</span>
      <span className="settings-hint">{hint}</span>
    </div>
  )
}
