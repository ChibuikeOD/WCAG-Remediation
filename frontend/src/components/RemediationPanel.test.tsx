import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { RemediationPanel } from './RemediationPanel'
import type { AccessibilityReport } from '../types'
import {
  downloadRemediatedFile,
  downloadRemediationReport,
  remediateDocument,
} from '../api'

vi.mock('../api', () => ({
  remediateDocument: vi.fn(),
  downloadRemediatedFile: vi.fn(),
  downloadRemediationReport: vi.fn(),
}))

const report: AccessibilityReport = {
  id: 'report-1',
  document: {
    filename: 'source.pdf',
    file_type: 'pdf',
    analyzed_at: '2026-07-05T00:00:00Z',
  },
  wcag_version: '2.2',
  target_level: 'AA',
  total_issues: 1,
  total_errors: 1,
  total_warnings: 0,
  total_passed: 0,
  total_manual_review: 0,
  principle_summaries: [],
  issues_by_principle: {},
  all_issues: [
    {
      id: 'issue-1',
      rule_id: 'pdf-title',
      rule_name: 'PDF title',
      principle: 'Perceivable',
      wcag_level: 'A',
      severity: 'error',
      status: 'fail',
      message: 'Missing title',
      element_location: { selector: 'Document' },
      automatable_fix: true,
      fix_suggestion: 'Add title',
      fixed: false,
    },
  ],
  created_at: '2026-07-05T00:00:00Z',
}

describe('RemediationPanel downloads', () => {
  beforeEach(() => {
    vi.mocked(remediateDocument).mockResolvedValue({
      report_id: 'report-1',
      total_fixed: 1,
      total_failed: 0,
      results: [{ issue_id: 'pdf-title', success: true, message: 'Fixed' }],
      remediation_report_filename: 'Remediation_Report_report-1.pdf',
    })
    vi.mocked(downloadRemediatedFile).mockResolvedValue(new Blob(['fixed']))
    vi.mocked(downloadRemediationReport).mockResolvedValue(new Blob(['report']))
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:download'),
      revokeObjectURL: vi.fn(),
    })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('uses authenticated API download helpers for remediation artifacts', async () => {
    render(
      <RemediationPanel
        report={report}
        onClose={vi.fn()}
        onComplete={vi.fn()}
      />
    )

    fireEvent.click(screen.getByRole('button', { name: /Apply 1 fix/i }))
    await screen.findByText('Remediation complete')
    fireEvent.click(screen.getByRole('button', { name: /Download Remediation Report/i }))
    await waitFor(() => {
      expect(downloadRemediationReport).toHaveBeenCalledWith('report-1')
    })
    fireEvent.click(screen.getByRole('button', { name: /Download Fixed PDF/i }))

    await waitFor(() => {
      expect(downloadRemediatedFile).toHaveBeenCalledWith('report-1')
    })
  })
})
