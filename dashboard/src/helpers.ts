/* ── Formatting helpers (ported from vanilla JS) ─────────── */

const INSTRUMENT_DISPLAY: Record<string, { name: string; category: string }> = {
  XAU_USD: { name: 'Gold', category: 'Commodities' },
  XAG_USD: { name: 'Silver', category: 'Commodities' },
  XPT_USD: { name: 'Platinum', category: 'Commodities' },
  WTICO_USD: { name: 'WTI Oil', category: 'Commodities' },
  NATGAS_USD: { name: 'Natural Gas', category: 'Commodities' },
}

export function instrumentLabel(inst: string): string {
  const info = INSTRUMENT_DISPLAY[inst]
  return info ? info.name : (inst ?? '').replace('_', '/')
}

export function instrumentCategory(inst: string): string {
  const info = INSTRUMENT_DISPLAY[inst]
  return info ? info.category : 'Forex'
}

export function fmt$(v: number | null | undefined): string {
  if (v == null) return '—'
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  if (isNaN(n)) return '—'
  return '$' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—'
  return parseFloat(String(v)).toFixed(2) + '%'
}

export function fmtPrice(v: number | null | undefined, digits = 5): string {
  if (v == null) return '—'
  return parseFloat(String(v)).toFixed(digits)
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC' }) + ' UTC'
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const now = new Date()
  const sameYear = d.getUTCFullYear() === now.getUTCFullYear()
  const dateOpts: Intl.DateTimeFormatOptions = sameYear
    ? { day: '2-digit', month: 'short', timeZone: 'UTC' }
    : { day: '2-digit', month: 'short', year: '2-digit', timeZone: 'UTC' }
  const date = d.toLocaleDateString('en-GB', dateOpts)
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
  return `${date} ${time}`
}

export function fmtDuration(openIso: string | null | undefined, closeIso: string | null | undefined): string {
  if (!openIso || !closeIso) return '—'
  const ms = new Date(closeIso).getTime() - new Date(openIso).getTime()
  if (ms < 0) return '—'
  const secs = Math.floor(ms / 1000)
  if (secs < 60) return `${secs}s`
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m`
  const hrs = Math.floor(mins / 60)
  const remMins = mins % 60
  if (hrs < 24) return `${hrs}h ${remMins}m`
  const days = Math.floor(hrs / 24)
  return `${days}d ${hrs % 24}h`
}

export function formatUptime(secs: number | null | undefined): string {
  if (!secs || secs <= 0) return '▲ 0h0m'
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  return `▲ ${h}h${m}m`
}

export function pnlClass(v: number | null | undefined): string {
  if (v == null) return 'neutral'
  return v >= 0 ? 'positive' : 'negative'
}

export function priceDigits(pair: string | null | undefined): number {
  if (pair && pair.indexOf('XAU') >= 0) return 2
  return 5
}
