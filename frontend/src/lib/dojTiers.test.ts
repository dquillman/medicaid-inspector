import { describe, expect, it } from 'vitest'
import { rowBadge } from './dojTiers'

describe('rowBadge', () => {
  it('names exclusion findings plainly', () => {
    expect(rowBadge({ tier: 2, kind: 'active_exclusion' }).label).toBe('Paid while excluded')
    expect(rowBadge({ tier: 2, kind: 'excluded_servicing' }).label).toBe('Paid while excluded')
  })
  it('keeps the status label for the other per-se findings', () => {
    for (const kind of ['medicare_revoked_billing', 'paid_while_terminated', 'deactivated_billing', 'deactivated_window']) {
      expect(rowBadge({ tier: 2, kind }).label).toBe('Status discrepancy')
    }
  })
  it('leaves tiers 1 and 3 alone', () => {
    expect(rowBadge({ tier: 1 }).label).toBe('Your worked cases')
    expect(rowBadge({ tier: 3 }).label).toBe('Brain leads (DOJ areas)')
  })
})
