import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Building2, Check, CreditCard, FileText } from 'lucide-react';
import {
  createCheckoutSession,
  createSubscriptionCheckoutSession,
  getBillingCatalog,
  requestInstitutionalInvoice,
  type BillingCatalog,
  type BillingServiceMode,
  type UserSession,
} from '../api';

type PackKey = 'starter' | 'standard' | 'pro';
type PlanKey = 'community' | 'library' | 'campus';

const fallbackCatalog: BillingCatalog = {
  currency: 'usd',
  credit_validity_months: 12,
  service_modes: {
    remediation: {
      label: 'Full remediation',
      pay_as_you_go: {
        starter: { name: 'Starter', pages: 250, amount_cents: 4900, per_page_cents: 20, notes: 'Post-trial bump from 400 free' },
        standard: { name: 'Standard', pages: 1000, amount_cents: 14900, per_page_cents: 15, notes: 'Small library backlog' },
        pro: { name: 'Pro', pages: 5000, amount_cents: 59900, per_page_cents: 12, notes: 'Department-level' },
      },
      institutional_annual: {
        community: { name: 'Community', annual_price_cents: 39900, pages: 2500, overage_cents: 18, best_for: 'Small public library' },
        library: { name: 'Library', annual_price_cents: 89900, pages: 8000, overage_cents: 14, best_for: 'Mid-size system' },
        campus: { name: 'Campus', annual_price_cents: 249900, pages: 30000, overage_cents: 10, best_for: 'University, large district' },
      },
    },
    audit: {
      label: 'Audit/report only',
      pay_as_you_go: {
        starter: { name: 'Starter', pages: 250, amount_cents: 2500, per_page_cents: 10, notes: 'Post-trial bump from 400 free' },
        standard: { name: 'Standard', pages: 1000, amount_cents: 7500, per_page_cents: 8, notes: 'Small library backlog' },
        pro: { name: 'Pro', pages: 5000, amount_cents: 30000, per_page_cents: 6, notes: 'Department-level' },
      },
      institutional_annual: {
        community: { name: 'Community', annual_price_cents: 19900, pages: 2500, overage_cents: 9, best_for: 'Small public library' },
        library: { name: 'Library', annual_price_cents: 44900, pages: 8000, overage_cents: 7, best_for: 'Mid-size system' },
        campus: { name: 'Campus', annual_price_cents: 124900, pages: 30000, overage_cents: 5, best_for: 'University, large district' },
      },
    },
  },
  institutional_terms: {
    shared_org_account: true,
    domain_verification: ['.edu', '.org', '.gov'],
    invoice_and_po: true,
    annual_true_up_at_renewal: true,
  },
};

function money(cents: number): string {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: cents % 100 === 0 ? 0 : 2,
  }).format(cents / 100);
}

function pages(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

export function BillingPanel({ user }: { user: UserSession | null }) {
  const [catalog, setCatalog] = useState<BillingCatalog>(fallbackCatalog);
  const [serviceMode, setServiceMode] = useState<BillingServiceMode>('remediation');
  const [selectedPlan, setSelectedPlan] = useState<PlanKey>('library');
  const [organizationName, setOrganizationName] = useState('');
  const [contactName, setContactName] = useState(user?.name ?? '');
  const [contactEmail, setContactEmail] = useState(user?.email ?? '');
  const [poNumber, setPoNumber] = useState('');
  const [isCheckingOut, setIsCheckingOut] = useState<PackKey | null>(null);
  const [isSubscribing, setIsSubscribing] = useState(false);
  const [isSubmittingInvoice, setIsSubmittingInvoice] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;
    getBillingCatalog()
      .then((nextCatalog) => {
        if (mounted) setCatalog(nextCatalog);
      })
      .catch(() => {
        if (mounted) setCatalog(fallbackCatalog);
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    setContactName((current) => current || user?.name || '');
    setContactEmail((current) => current || user?.email || '');
  }, [user?.email, user?.name]);

  const modeCatalog = catalog.service_modes[serviceMode];
  const packEntries = useMemo(
    () => Object.entries(modeCatalog.pay_as_you_go) as Array<[PackKey, typeof modeCatalog.pay_as_you_go[PackKey]]>,
    [modeCatalog.pay_as_you_go],
  );
  const planEntries = useMemo(
    () => Object.entries(modeCatalog.institutional_annual) as Array<[PlanKey, typeof modeCatalog.institutional_annual[PlanKey]]>,
    [modeCatalog.institutional_annual],
  );

  async function startCheckout(packKey: PackKey) {
    setError(null);
    setMessage(null);
    setIsCheckingOut(packKey);
    try {
      const session = await createCheckoutSession({ pack_key: packKey, service_mode: serviceMode });
      window.location.assign(session.url);
    } catch (checkoutError) {
      setError(checkoutError instanceof Error ? checkoutError.message : 'Unable to open Stripe checkout.');
    } finally {
      setIsCheckingOut(null);
    }
  }

  async function submitInvoiceRequest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setMessage(null);
    setIsSubmittingInvoice(true);
    try {
      const result = await requestInstitutionalInvoice({
        plan_key: selectedPlan,
        service_mode: serviceMode,
        organization_name: organizationName,
        contact_name: contactName,
        contact_email: contactEmail,
        po_number: poNumber || undefined,
      });
      setMessage(
        result.domain_verified
          ? 'Invoice request received with institutional domain verification.'
          : 'Invoice request received for manual domain review.',
      );
    } catch (invoiceError) {
      setError(invoiceError instanceof Error ? invoiceError.message : 'Unable to submit invoice request.');
    } finally {
      setIsSubmittingInvoice(false);
    }
  }

  async function startSubscriptionCheckout() {
    setError(null);
    setMessage(null);
    setIsSubscribing(true);
    try {
      const session = await createSubscriptionCheckoutSession({
        plan_key: selectedPlan,
        service_mode: serviceMode,
      });
      window.location.assign(session.url);
    } catch (subscriptionError) {
      setError(subscriptionError instanceof Error ? subscriptionError.message : 'Unable to open subscription checkout.');
    } finally {
      setIsSubscribing(false);
    }
  }

  return (
    <section className="mt-16 space-y-6" aria-labelledby="billing-heading">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider" style={{ color: '#60a5fa' }}>
            Payments
          </p>
          <h2 id="billing-heading" className="mt-2 text-2xl font-semibold" style={{ color: '#e8edf4' }}>
            Page credits and institutional billing
          </h2>
        </div>
        <div
          className="inline-flex w-fit items-center gap-1 rounded-lg p-1"
          style={{ background: '#0d1420', border: '1px solid #1a2840' }}
          role="group"
          aria-label="Billing service mode"
        >
          {(['remediation', 'audit'] as const).map((mode) => (
            <button
              key={mode}
              type="button"
              onClick={() => setServiceMode(mode)}
              className="rounded-md px-3 py-1.5 text-sm font-medium transition-colors"
              style={serviceMode === mode ? { background: '#2563eb', color: '#fff' } : { color: '#7a90a8' }}
              aria-pressed={serviceMode === mode}
            >
              {catalog.service_modes[mode].label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {packEntries.map(([key, pack]) => (
          <article key={key} className="card flex min-h-[236px] flex-col gap-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-base font-semibold" style={{ color: '#e8edf4' }}>
                  {pack.name}
                </h3>
                <p className="mt-1 text-sm" style={{ color: '#7a90a8' }}>
                  {pages(pack.pages)} pages
                </p>
              </div>
              <CreditCard className="h-5 w-5 shrink-0" style={{ color: '#60a5fa' }} aria-hidden="true" />
            </div>
            <div>
              <p className="text-3xl font-semibold" style={{ color: '#f8fafc' }}>
                {money(pack.amount_cents)}
              </p>
              <p className="mt-1 text-sm" style={{ color: '#7a90a8' }}>
                {money(pack.per_page_cents)}/page
              </p>
            </div>
            <p className="min-h-[40px] text-sm leading-relaxed" style={{ color: '#7a90a8' }}>
              {pack.notes}
            </p>
            <button
              type="button"
              className="btn btn-primary mt-auto"
              onClick={() => void startCheckout(key)}
              disabled={isCheckingOut !== null}
            >
              <CreditCard className="h-4 w-4" aria-hidden="true" />
              {isCheckingOut === key ? 'Opening Stripe' : 'Pay by card'}
            </button>
          </article>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="card">
          <div className="mb-5 flex items-center gap-3">
            <Building2 className="h-5 w-5" style={{ color: '#60a5fa' }} aria-hidden="true" />
            <h3 className="text-base font-semibold" style={{ color: '#e8edf4' }}>
              Institutional annual
            </h3>
          </div>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {planEntries.map(([key, plan]) => (
              <button
                key={key}
                type="button"
                onClick={() => setSelectedPlan(key)}
                className="rounded-lg border p-4 text-left transition-colors"
                style={
                  selectedPlan === key
                    ? { borderColor: '#2563eb', background: 'rgba(37,99,235,0.10)' }
                    : { borderColor: '#1a2840', background: '#0d1420' }
                }
                aria-pressed={selectedPlan === key}
              >
                <span className="block text-sm font-semibold" style={{ color: '#e8edf4' }}>
                  {plan.name}
                </span>
                <span className="mt-2 block text-xl font-semibold" style={{ color: '#f8fafc' }}>
                  {money(plan.annual_price_cents)}/yr
                </span>
                <span className="mt-2 block text-xs leading-relaxed" style={{ color: '#7a90a8' }}>
                  {pages(plan.pages)} pages, {money(plan.overage_cents)}/page overage
                </span>
                <span className="mt-3 block text-xs" style={{ color: '#4a607a' }}>
                  {plan.best_for}
                </span>
              </button>
            ))}
          </div>
          <div className="mt-5 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2" style={{ color: '#7a90a8' }}>
            <span className="flex items-center gap-2"><Check className="h-4 w-4" aria-hidden="true" /> Shared org account</span>
            <span className="flex items-center gap-2"><Check className="h-4 w-4" aria-hidden="true" /> .edu / .org / .gov verification</span>
            <span className="flex items-center gap-2"><Check className="h-4 w-4" aria-hidden="true" /> Invoice + PO</span>
            <span className="flex items-center gap-2"><Check className="h-4 w-4" aria-hidden="true" /> Annual true-up</span>
          </div>
          <button
            type="button"
            className="btn btn-primary mt-5"
            onClick={() => void startSubscriptionCheckout()}
            disabled={isSubscribing}
          >
            <CreditCard className="h-4 w-4" aria-hidden="true" />
            {isSubscribing ? 'Opening subscription' : 'Subscribe by card'}
          </button>
        </div>

        <form className="card space-y-4" onSubmit={(event) => void submitInvoiceRequest(event)}>
          <div className="flex items-center gap-3">
            <FileText className="h-5 w-5" style={{ color: '#60a5fa' }} aria-hidden="true" />
            <h3 className="text-base font-semibold" style={{ color: '#e8edf4' }}>
              Invoice / PO
            </h3>
          </div>
          <label className="block text-sm font-medium" style={{ color: '#cbd5e1' }}>
            Organization
            <input
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
              style={{ background: '#080c14', borderColor: '#1a2840', color: '#e8edf4' }}
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm font-medium" style={{ color: '#cbd5e1' }}>
            Contact
            <input
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
              style={{ background: '#080c14', borderColor: '#1a2840', color: '#e8edf4' }}
              value={contactName}
              onChange={(event) => setContactName(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm font-medium" style={{ color: '#cbd5e1' }}>
            Email
            <input
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
              style={{ background: '#080c14', borderColor: '#1a2840', color: '#e8edf4' }}
              type="email"
              value={contactEmail}
              onChange={(event) => setContactEmail(event.target.value)}
              required
            />
          </label>
          <label className="block text-sm font-medium" style={{ color: '#cbd5e1' }}>
            PO number
            <input
              className="mt-1 w-full rounded-lg border px-3 py-2 text-sm"
              style={{ background: '#080c14', borderColor: '#1a2840', color: '#e8edf4' }}
              value={poNumber}
              onChange={(event) => setPoNumber(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-secondary w-full" disabled={isSubmittingInvoice}>
            <FileText className="h-4 w-4" aria-hidden="true" />
            {isSubmittingInvoice ? 'Submitting' : 'Request invoice'}
          </button>
          {message && <p className="text-sm" style={{ color: '#86efac' }}>{message}</p>}
          {error && <p role="alert" className="text-sm" style={{ color: '#fca5a5' }}>{error}</p>}
        </form>
      </div>
    </section>
  );
}
