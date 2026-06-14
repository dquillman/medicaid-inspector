import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'

/**
 * App-wide per-provider membership flags — fetched ONCE (watchlist set + Fraud
 * Brain top-N rank map) and read by the <ProviderFlags> badge anywhere a
 * provider appears. React-Query dedupes, so every page shares one fetch.
 */
interface Flags {
  isWatched: (npi: string) => boolean
  brainRank: (npi: string) => number | undefined
}

const Ctx = createContext<Flags>({ isWatched: () => false, brainRank: () => undefined })

export function ProviderFlagsProvider({ children }: { children: ReactNode }) {
  const { data: wl } = useQuery({
    queryKey: ['watchlist-set'],
    queryFn: () => api.watchlist(),
    staleTime: 5 * 60_000,
    retry: 1,
  })
  const { data: brain } = useQuery({
    queryKey: ['brain-membership'],
    queryFn: () => api.fraudBrainMembership(100),
    staleTime: 5 * 60_000,
    retry: 1,
  })

  const value = useMemo<Flags>(() => {
    const watched = new Set((wl?.items ?? []).map((e) => e.npi))
    const ranks = brain?.members ?? {}
    return {
      isWatched: (npi) => watched.has(npi),
      brainRank: (npi) => ranks[npi],
    }
  }, [wl, brain])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useProviderFlags = () => useContext(Ctx)
