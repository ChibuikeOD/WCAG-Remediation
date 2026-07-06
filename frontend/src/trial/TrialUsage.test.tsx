import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { TrialUsage } from './TrialUsage'

describe('TrialUsage', () => {
  it('shows the remaining page balance and a text-backed progress meter', () => {
    render(
      <TrialUsage
        balance={{
          granted_pages: 400,
          consumed_pages: 120,
          reserved_pages: 20,
          remaining_pages: 260,
          normalized_domain: 'university.edu',
          eligibility_rule_version: '2026-07-04',
        }}
      />,
    )

    expect(screen.getByText(/260 of 400 trial pages remaining/i)).toBeInTheDocument()
    expect(screen.getByText(/120 consumed/i)).toBeInTheDocument()
    expect(screen.getByText(/20 reserved/i)).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: /Trial pages used/i })).toHaveAttribute(
      'aria-valuenow',
      '140',
    )
  })
})
