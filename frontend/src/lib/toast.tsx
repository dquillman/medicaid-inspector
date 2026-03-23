import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { ToastContainer } from '../components/Toast'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
  id: string
  message: string
  type: ToastType
  duration: number
  createdAt: number
}

interface ToastContextType {
  addToast: (message: string, type: ToastType, duration?: number) => void
}

const ToastContext = createContext<ToastContextType | null>(null)

const DEFAULT_DURATION = 5000

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])

  const addToast = useCallback((message: string, type: ToastType, duration = DEFAULT_DURATION) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
    const toast: Toast = { id, message, type, duration, createdAt: Date.now() }
    setToasts(prev => [...prev, toast])
  }, [])

  const removeToast = useCallback((id: string) => {
    setToasts(prev => prev.filter(t => t.id !== id))
  }, [])

  return (
    <ToastContext.Provider value={{ addToast }}>
      {children}
      {createPortal(
        <ToastContainer toasts={toasts} onDismiss={removeToast} />,
        document.body
      )}
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')

  return {
    success: (msg: string) => ctx.addToast(msg, 'success'),
    error: (msg: string) => ctx.addToast(msg, 'error'),
    warning: (msg: string) => ctx.addToast(msg, 'warning'),
    info: (msg: string) => ctx.addToast(msg, 'info'),
    addToast: ctx.addToast,
  }
}
