import { type ReactNode, useCallback, useRef } from 'react'

interface CardProps {
  id: string
  title: string
  collapsed: boolean
  onToggle: (id: string) => void
  badge?: ReactNode
  collapsedContent?: ReactNode
  onDragStart?: (e: React.DragEvent, id: string) => void
  onDragOver?: (e: React.DragEvent, id: string) => void
  onDragLeave?: (e: React.DragEvent) => void
  onDrop?: (e: React.DragEvent, id: string) => void
  onDragEnd?: () => void
  dragOverClass?: string
  isDragging?: boolean
  children: ReactNode
}

export default function Card({
  id, title, collapsed, onToggle, badge, collapsedContent,
  onDragStart, onDragOver, onDragLeave, onDrop, onDragEnd,
  dragOverClass, isDragging, children,
}: CardProps) {
  const handleToggle = useCallback(() => onToggle(id), [id, onToggle])
  const allowDrag = useRef(false)

  const cls = [
    'card',
    isDragging ? 'dragging' : '',
    dragOverClass ?? '',
  ].filter(Boolean).join(' ')

  return (
    <div
      id={id}
      className={cls}
      draggable={allowDrag.current}
      onDragStart={onDragStart ? (e) => {
        if (!allowDrag.current) { e.preventDefault(); return }
        onDragStart(e, id)
      } : undefined}
      onDragOver={onDragOver ? (e) => onDragOver(e, id) : undefined}
      onDragLeave={onDragLeave}
      onDrop={onDrop ? (e) => onDrop(e, id) : undefined}
      onDragEnd={() => { allowDrag.current = false; onDragEnd?.() }}
    >
      <div className="card-title" onClick={handleToggle}>
        <span>
          <span
            className="drag-handle"
            title="Drag to reorder"
            onMouseDown={() => { allowDrag.current = true }}
            onMouseUp={() => { allowDrag.current = false }}
          >⠿</span>
          <span className={`chevron${collapsed ? ' collapsed' : ''}`}>▾</span>
          {title}
        </span>
        <span className="card-title-right">
          {collapsed && collapsedContent && <span className="collapsed-preview">{collapsedContent}</span>}
          {badge && <span className="count mono">{badge}</span>}
        </span>
      </div>
      {!collapsed && <div className="card-body">{children}</div>}
    </div>
  )
}
