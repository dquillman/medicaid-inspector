import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ToastProvider } from './lib/toast'
import { AuthProvider } from './lib/auth'
import App from './App'
import { applyMotionPref } from './lib/motionPref'
import './index.css'

// Mirror the saved Motion preference onto <html data-motion> before first paint
// so the CSS reduced-motion backstop respects a forced-on/off choice immediately.
applyMotionPref()

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      retry: 1,
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <App />
        </ToastProvider>
      </QueryClientProvider>
    </AuthProvider>
  </React.StrictMode>,
)
