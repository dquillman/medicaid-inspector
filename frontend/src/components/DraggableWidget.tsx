import { useState, useCallback, type ReactNode, type DragEvent } from 'react'

interface DraggableWidgetProps {
  id: string
  index: number
  onDragStart?: (e: DragEvent<HTMLDivElement>, index: number) => void
  onDragOver?: (e: DragEvent<HTMLDivElement>, index: number) => void
  onDrop: (e: DragEvent<HTMLDivElement>, index: number) => void
  children: ReactNode
}

export default function DraggableWidget({
  id,
  index,
  onDragStart,
  onDragOver,
  onDrop,
  children,
}: DraggableWidgetProps) {
  const [isDragging, setIsDragging] = useState(false)
  const [isDragOver, setIsDragOver] = useState(false)

  const handleDragStart = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.dataTransfer.setData('text/plain', String(index))
      e.dataTransfer.effectAllowed = 'move'
      setIsDragging(true)
      onDragStart?.(e, index)
    },
    [index, onDragStart],
  )

  const handleDragEnd = useCallback(() => {
    setIsDragging(false)
  }, [])

  const handleDragOver = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      setIsDragOver(true)
      onDragOver?.(e, index)
    },
    [index, onDragOver],
  )

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false)
  }, [])

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setIsDragOver(false)
      onDrop(e, index)
    },
    [index, onDrop],
  )

  return (
    <div
      data-widget-id={id}
      className={`group relative transition-all duration-200 ${
        isDragging ? 'opacity-50' : ''
      } ${isDragOver ? 'border-2 border-dashed border-blue-500/50 rounded-xl' : ''}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <div
        draggable
        onDragStart={handleDragStart}
        onDragEnd={handleDragEnd}
        className="absolute top-2 right-2 z-10 cursor-grab active:cursor-grabbing opacity-0 group-hover:opacity-100 transition-opacity p-1.5 rounded-md hover:bg-gray-700/60 text-gray-500 hover:text-gray-300"
        title="Drag to reorder"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="currentColor"
          xmlns="http://www.w3.org/2000/svg"
        >
          <circle cx="5" cy="3" r="1.5" />
          <circle cx="11" cy="3" r="1.5" />
          <circle cx="5" cy="8" r="1.5" />
          <circle cx="11" cy="8" r="1.5" />
          <circle cx="5" cy="13" r="1.5" />
          <circle cx="11" cy="13" r="1.5" />
        </svg>
      </div>
      {children}
    </div>
  )
}
