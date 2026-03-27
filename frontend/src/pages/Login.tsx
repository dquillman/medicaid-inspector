import { useState } from 'react'

interface Props {
  onLogin: (username: string, password: string) => Promise<string | null>
  onRegister: (username: string, password: string, displayName?: string) => Promise<string | null>
  onBack: () => void
}

export default function Login({ onLogin, onRegister, onBack }: Props) {
  const [isSignUp, setIsSignUp] = useState(false)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (!username || !password) {
      setError('Username and password are required')
      return
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters')
      return
    }

    setLoading(true)
    try {
      const err = isSignUp
        ? await onRegister(username, password, displayName || undefined)
        : await onLogin(username, password)
      if (err) setError(err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="w-full max-w-sm">
        {/* Logo */}
        <div className="text-center mb-8">
          <div className="flex items-center justify-center gap-2.5 mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" className="w-10 h-10">
              <path d="M32 4 L56 14 L56 34 C56 48 44 58 32 62 C20 58 8 48 8 34 L8 14 Z" fill="#1e3a5f"/>
              <path d="M32 7 L53 16 L53 34 C53 46.5 42.5 56 32 59.5 C21.5 56 11 46.5 11 34 L11 16 Z" fill="none" stroke="#3b82f6" strokeWidth="1.5"/>
              <circle cx="28" cy="28" r="11" fill="none" stroke="#60a5fa" strokeWidth="4"/>
              <circle cx="28" cy="28" r="7" fill="#1e3a5f"/>
              <text x="28" y="33" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="11" fill="#f59e0b">$</text>
              <line x1="36" y1="36" x2="45" y2="45" stroke="#60a5fa" strokeWidth="4.5" strokeLinecap="round"/>
              <circle cx="46" cy="18" r="6" fill="#ef4444"/>
              <text x="46" y="22" textAnchor="middle" fontFamily="Arial, sans-serif" fontWeight="bold" fontSize="9" fill="white">!</text>
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-white">{isSignUp ? 'Create Account' : 'Welcome Back'}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {isSignUp ? 'Sign up for Medicaid Inspector' : 'Sign in to Medicaid Inspector'}
          </p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="card space-y-4">
          {error && (
            <div className="bg-red-950/50 border border-red-800 rounded-lg px-3 py-2 text-sm text-red-400">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Username</label>
            <input
              type="text"
              value={username}
              onChange={e => setUsername(e.target.value)}
              className="input w-full"
              placeholder="username"
              autoFocus
            />
          </div>

          {isSignUp && (
            <div>
              <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                className="input w-full"
                placeholder="Your Name (optional)"
              />
            </div>
          )}

          <div>
            <label className="block text-xs text-gray-400 mb-1.5 uppercase tracking-wider">Password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="input w-full"
              placeholder="********"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white py-2.5 rounded-lg font-semibold text-sm transition-colors"
          >
            {loading ? (isSignUp ? 'Creating account...' : 'Signing in...') : (isSignUp ? 'Create Account' : 'Sign In')}
          </button>
        </form>

        <div className="text-center mt-4 space-y-2">
          <button
            onClick={() => { setIsSignUp(!isSignUp); setError('') }}
            className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
          >
            {isSignUp ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
          </button>
          <div>
            <button onClick={onBack} className="text-xs text-gray-600 hover:text-gray-400 transition-colors">
              &larr; Back to home
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
