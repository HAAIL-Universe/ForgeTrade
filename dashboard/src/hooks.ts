import { useState, useEffect, useRef, useCallback } from 'react'

/**
 * Poll an async fetcher every `intervalMs` milliseconds.
 * Returns [data, error, lastUpdated, refresh].  Re-fetches immediately when deps change.
 * Call `refresh()` to trigger an immediate re-fetch outside the polling interval.
 */
export function usePolling<T>(
  fetcher: () => Promise<T>,
  intervalMs: number,
): [T | null, Error | null, number, () => void] {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [lastUpdated, setLastUpdated] = useState(0)
  const savedFetcher = useRef(fetcher)
  savedFetcher.current = fetcher

  const refresh = useCallback(async () => {
    try {
      const result = await savedFetcher.current()
      setData(result); setError(null); setLastUpdated(Date.now())
    } catch (e) {
      setError(e as Error)
    }
  }, [])

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        const result = await savedFetcher.current()
        if (!cancelled) { setData(result); setError(null); setLastUpdated(Date.now()) }
      } catch (e) {
        if (!cancelled) setError(e as Error)
      }
    }
    run()
    const id = setInterval(run, intervalMs)
    return () => { cancelled = true; clearInterval(id) }
  }, [intervalMs])

  return [data, error, lastUpdated, refresh]
}

/**
 * Persist a value in localStorage.
 */
export function useLocalStorage<T>(key: string, initial: T): [T, (v: T | ((prev: T) => T)) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = localStorage.getItem(key)
      return stored ? JSON.parse(stored) : initial
    } catch { return initial }
  })

  const set = useCallback((v: T | ((prev: T) => T)) => {
    setValue(prev => {
      const next = typeof v === 'function' ? (v as (prev: T) => T)(prev) : v
      try { localStorage.setItem(key, JSON.stringify(next)) } catch { /* noop */ }
      return next
    })
  }, [key])

  return [value, set]
}
