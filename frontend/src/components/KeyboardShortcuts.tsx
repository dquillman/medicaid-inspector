import { useState, useEffect } from 'react'

function Kbd({ children }: { children: string }) {
  return (
    <kbd className="inline-flex items-center px-2 py-1 bg-gray-800 border border-gray-600 rounded text-xs font-mono text-gray-300 min-w-[28px] justify-center">
      {children}
    </kbd>
  )
}

const SHORTCUTS = [
  {
    category: 'Navigation',
    items: [
      { keys: ['j', '\u2193'], desc: 'Next item in list' },
      { keys: ['k', '\u2191'], desc: 'Previous item in list' },
      { keys: ['Enter'], desc: 'Open selected item' },
      { keys: ['Esc'], desc: 'Close modal / overlay' },
    ],
  },
  {
    category: 'Search',
    items: [
      { keys: ['Ctrl', 'K'], desc: 'Open command palette', compound: true },
      { keys: ['/'], desc: 'Focus search field' },
    ],
  },
  {
    category: 'Interface',
    items: [
      { keys: ['?'], desc: 'Show this help' },
    ],
  },
]

export default function KeyboardShortcuts() {
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === '?') {
        e.preventDefault()
        setIsOpen(prev => !prev)
      }
      if (e.key === 'Escape') setIsOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-[60] bg-black/60"
      onClick={() => setIsOpen(false)}
    >
      <div
        className="bg-gray-900 border border-gray-700 rounded-xl w-full max-w-lg mx-auto mt-[15vh] p-6 relative"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold text-white">Keyboard Shortcuts</h2>
          <button
            onClick={() => setIsOpen(false)}
            className="text-gray-400 hover:text-white transition-colors"
            aria-label="Close"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {SHORTCUTS.map(section => (
          <div key={section.category}>
            <h3 className="text-xs text-gray-500 uppercase tracking-wider mb-2 mt-4">
              {section.category}
            </h3>
            <div className="space-y-2">
              {section.items.map(item => (
                <div key={item.desc} className="flex items-center justify-between">
                  <div className="flex items-center gap-1">
                    {item.compound ? (
                      <>
                        <Kbd>{item.keys[0]}</Kbd>
                        <span className="text-xs text-gray-500">+</span>
                        <Kbd>{item.keys[1]}</Kbd>
                      </>
                    ) : (
                      item.keys.map((k, i) => (
                        <span key={k} className="flex items-center gap-1">
                          {i > 0 && <span className="text-xs text-gray-500">or</span>}
                          <Kbd>{k}</Kbd>
                        </span>
                      ))
                    )}
                  </div>
                  <span className="text-sm text-gray-400">{item.desc}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
