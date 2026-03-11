import { useState, useRef, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useClickOutside } from '../hooks/useClickOutside'
import { get, mutate } from '../lib/api'

interface Notification {
  id: string
  type: 'alert' | 'watchlist' | 'scan' | 'system'
  title: string
  message: string
  timestamp: number
  read: boolean
  link?: string
}

const TYPE_ICONS: Record<string, string> = {
  alert: '\u26A0',
  watchlist: '\uD83D\uDC41',
  scan: '\uD83D\uDD0D',
  system: '\u2699',
}

const TYPE_COLORS: Record<string, string> = {
  alert: 'text-red-400',
  watchlist: 'text-yellow-400',
  scan: 'text-blue-400',
  system: 'text-gray-400',
}

function timeAgo(ts: number): string {
  const now = Date.now() / 1000
  const diff = now - ts
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export default function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()

  const { data } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => get<{ notifications: Notification[]; unread_count: number }>('/notifications').catch(() => ({ notifications: [], unread_count: 0 })),
    refetchInterval: 30000,
  })

  const notifications: Notification[] = data?.notifications ?? []
  const unreadCount: number = data?.unread_count ?? 0

  useClickOutside(ref, useCallback(() => setOpen(false), []))

  const markRead = async (id: string) => {
    await mutate<{ ok: boolean }>('PATCH', `/notifications/${id}/read`)
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  const markAllRead = async () => {
    await mutate<{ ok: boolean }>('POST', '/notifications/read-all')
    queryClient.invalidateQueries({ queryKey: ['notifications'] })
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(!open)}
        className="relative text-gray-400 hover:text-white transition-colors p-1"
        aria-label="Notifications"
        title="Notifications"
      >
        <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0" />
        </svg>
        {unreadCount > 0 && (
          <span className="absolute -top-1 -right-1 bg-red-500 text-white text-[10px] font-bold rounded-full min-w-[16px] h-4 flex items-center justify-center px-1">
            {unreadCount > 99 ? '99+' : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute top-full right-0 mt-2 w-80 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 max-h-96 overflow-hidden flex flex-col">
          <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700">
            <span className="text-sm font-semibold text-white">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="text-xs text-blue-400 hover:text-blue-300"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="overflow-y-auto flex-1">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-gray-500 text-sm">
                No notifications yet
              </div>
            ) : (
              notifications.map(n => (
                <div
                  key={n.id}
                  className={`px-4 py-3 border-b border-gray-700/50 hover:bg-gray-700/50 cursor-pointer transition-colors ${
                    !n.read ? 'bg-gray-750/30' : ''
                  }`}
                  onClick={() => {
                    if (!n.read) markRead(n.id)
                    if (n.link) {
                      window.location.hash = ''
                      window.location.pathname = n.link
                    }
                    setOpen(false)
                  }}
                >
                  <div className="flex items-start gap-2">
                    <span className={`text-sm ${TYPE_COLORS[n.type] || 'text-gray-400'}`}>
                      {TYPE_ICONS[n.type] || '\u2022'}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-sm font-medium ${n.read ? 'text-gray-400' : 'text-white'}`}>
                          {n.title}
                        </span>
                        {!n.read && (
                          <span className="w-2 h-2 rounded-full bg-blue-500 shrink-0" />
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mt-0.5 truncate">{n.message}</p>
                      <p className="text-[10px] text-gray-600 mt-1">{timeAgo(n.timestamp)}</p>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
