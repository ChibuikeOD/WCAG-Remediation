import type { TrialBalance } from '../api'

interface TrialUsageProps {
  balance: TrialBalance
}

export function TrialUsage({ balance }: TrialUsageProps) {
  const usedPages = balance.consumed_pages + balance.reserved_pages
  const usedPercentage = balance.granted_pages
    ? Math.min(100, Math.round((usedPages / balance.granted_pages) * 100))
    : 0

  return (
    <section
      aria-label="Trial usage"
      className="min-w-56 rounded-lg border px-3 py-2"
      style={{ background: '#111c2d', borderColor: '#1a2840' }}
    >
      <p className="text-xs font-semibold" style={{ color: '#c8d8e8' }}>
        {balance.remaining_pages} of {balance.granted_pages} trial pages remaining
      </p>
      <div
        role="progressbar"
        aria-label="Trial pages used"
        aria-valuemin={0}
        aria-valuemax={balance.granted_pages}
        aria-valuenow={usedPages}
        aria-valuetext={`${balance.consumed_pages} consumed and ${balance.reserved_pages} reserved`}
        className="mt-2 h-1.5 overflow-hidden rounded-full"
        style={{ background: '#24354d' }}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${usedPercentage}%`, background: '#2dd4bf' }}
        />
      </div>
      <p className="mt-1.5 text-[11px]" style={{ color: '#7a90a8' }}>
        {balance.consumed_pages} consumed · {balance.reserved_pages} reserved
      </p>
    </section>
  )
}
