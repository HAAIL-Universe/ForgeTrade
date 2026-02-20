import { useState, useCallback, useRef, type ReactElement } from 'react'
import { useLocalStorage } from '../hooks'

interface Props {
  /** Card elements (must each have a key that doubles as its id) */
  children: ReactElement[]
}

const STORAGE_KEY = 'ft_card_order'

/**
 * Wraps card children in a drag-reorderable container.
 * Persists order to localStorage.
 */
export default function CardContainer({ children }: Props) {
  const [order, setOrder] = useLocalStorage<string[]>(STORAGE_KEY, [])
  const [dragSrcId, setDragSrcId] = useState<string | null>(null)
  const [overState, setOverState] = useState<{ id: string; half: 'above' | 'below' } | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Sort children by saved order (unrecognised ids go to the end in original order)
  const sortedChildren = (() => {
    if (!order.length) return children
    const byKey = new Map<string, ReactElement>()
    const allKeys: string[] = []
    children.forEach(c => {
      const k = String(c.key ?? '')
      byKey.set(k, c)
      allKeys.push(k)
    })
    const sorted: ReactElement[] = []
    const used = new Set<string>()
    for (const id of order) {
      const el = byKey.get(id)
      if (el) { sorted.push(el); used.add(id) }
    }
    for (const k of allKeys) {
      if (!used.has(k)) { const el = byKey.get(k); if (el) sorted.push(el) }
    }
    return sorted
  })()

  const handleDragStart = useCallback((e: React.DragEvent, id: string) => {
    setDragSrcId(id)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', id)
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent, id: string) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (id === dragSrcId) { setOverState(null); return }
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const half = e.clientY < rect.top + rect.height / 2 ? 'above' : 'below'
    setOverState({ id, half })
  }, [dragSrcId])

  const handleDragLeave = useCallback(() => setOverState(null), [])

  const handleDrop = useCallback((e: React.DragEvent, targetId: string) => {
    e.preventDefault()
    if (!dragSrcId || dragSrcId === targetId) return

    const currentOrder = sortedChildren.map(c => String(c.key ?? ''))
    const srcIdx = currentOrder.indexOf(dragSrcId)
    let tgtIdx = currentOrder.indexOf(targetId)
    if (srcIdx < 0 || tgtIdx < 0) return

    // Remove source
    currentOrder.splice(srcIdx, 1)
    // Recalculate target index after removal
    tgtIdx = currentOrder.indexOf(targetId)
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
    const insertIdx = e.clientY < rect.top + rect.height / 2 ? tgtIdx : tgtIdx + 1
    currentOrder.splice(insertIdx, 0, dragSrcId)

    setOrder(currentOrder)
    setOverState(null)
    setDragSrcId(null)
  }, [dragSrcId, sortedChildren, setOrder])

  const handleDragEnd = useCallback(() => {
    setDragSrcId(null)
    setOverState(null)
  }, [])

  return (
    <div
      ref={containerRef}
      id="card-container"
      className={dragSrcId ? 'drag-active' : ''}
    >
      {sortedChildren.map(child => {
        const childId = String(child.key ?? '')
        const isOver = overState?.id === childId
        const dragOverClass = isOver
          ? overState.half === 'above' ? 'drag-over-above' : 'drag-over-below'
          : undefined

        // Clone to inject drag props
        return (
          <div key={childId} style={{ display: 'contents' }}>
            {typeof child.type === 'function' || typeof child.type === 'object'
              ? (() => {
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  const Child = child.type as any
                  const childProps = (child.props ?? {}) as Record<string, unknown>
                  return (
                    <Child
                      {...childProps}
                      onDragStart={handleDragStart}
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                      onDragEnd={handleDragEnd}
                      dragOverClass={dragOverClass}
                      isDragging={dragSrcId === childId}
                    />
                  )
                })()
              : child
            }
          </div>
        )
      })}
    </div>
  )
}
