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
  brainScore: (npi: string) => number | undefined
  isTipped: (npi: string) => boolean
  /** False until the Brain membership fetch resolves. brainScore() returns
   *  undefined BOTH while loading and when a provider is genuinely off-board;
   *  without this, callers cannot tell "not on the board" from "don't know
   *  yet" — the MFCU eligibility gate read a still-loading fetch as "off
   *  board" and declared a #2-ranked provider NOT ELIGIBLE. */
  brainLoaded: boolean
}

const Ctx = createContext<Flags>({ isWatched: () => false, brainRank: () => undefined, brainScore: () => undefined, isTipped: () => false, brainLoaded: false })

export function ProviderFlagsProvider({ children }: { children: ReactNode }) {
  const { data: wl } = useQuery({
    queryKey: ['watchlist-set'],
    queryFn: () => api.watchlist(),
    staleTime: 5 * 60_000,
    retry: 1,
  })
  const { data: brain, isSuccess: brainOk } = useQuery({
    queryKey: ['brain-membership'],
    // 500 (the backend cap) rather than 100 — Brain-flag parity (#2): analysis
    // pages like Claim Patterns / Billing Codes surface providers well past the
    // top-100, and the BRAIN chip should appear for any provider on the board.
    queryFn: () => api.fraudBrainMembership(500),
    // Keep the Review Queue's Brain scores in lockstep with the Fraud Brain
    // board. This provider mounts ONCE at app level, so page navigation never
    // remounts it — without a poll, a snapshot cached before a board recompute
    // (or a backend cold start) lingers and disagrees with the board. The
    // membership endpoint serves from the backend's 15-min cache (a cheap,
    // near-instant read), so polling every 60s is cheap insurance against drift,
    // on top of refetch-on-focus and the explicit invalidation the board's
    // Recompute / case-prep actions fire.
    staleTime: 60_000,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    retry: 1,
  })
  const { data: tips } = useQuery({
    queryKey: ['oig-tips-filed'],
    queryFn: () => api.oigTipsFiled(),
    staleTime: 5 * 60_000,
    retry: 1,
  })

  const value = useMemo<Flags>(() => {
    const watched = new Set((wl?.items ?? []).map((e) => e.npi))
    const ranks = brain?.members ?? {}
    const scores = brain?.scores ?? {}
    const tipped = new Set(tips?.npis ?? [])
    return {
      isWatched: (npi) => watched.has(npi),
      brainRank: (npi) => ranks[npi],
      brainScore: (npi) => scores[npi],
      isTipped: (npi) => tipped.has(npi),
      brainLoaded: brainOk,
    }
  }, [wl, brain, tips, brainOk])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export const useProviderFlags = () => useContext(Ctx)
