import type { ProviderStatus, RunConditions } from "@/lib/api";

export function ProviderNotConfigured({ providers }: { providers: ProviderStatus[] }) {
  if (providers.some((p) => p.configured)) return null;
  const p = providers[0];
  return (
    <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
      <p className="font-semibold">AI visibility testing is not set up</p>
      <p className="mt-1">
        No AI provider credentials are configured, so no AI answers can be collected — and none are simulated. The website
        audit, question generation (from templates) and audit recommendations still work.
      </p>
      {p?.setup_instructions && (
        <p className="mt-2">
          <span className="font-medium">To enable {p.display_name}:</span> {p.setup_instructions}
        </p>
      )}
    </div>
  );
}

export function RunConditionsNote({ conditions, when }: { conditions: RunConditions; when?: string }) {
  return (
    <p className="text-xs leading-relaxed text-slate-500">
      Real responses from <span className="font-medium text-slate-700">{String(conditions.provider)}</span> API, model{" "}
      <span className="font-mono">{String(conditions.model)}</span>
      {conditions.web_search ? ", with web search" : ", without web search"}
      {when && <>, collected {when}</>}. API answers may differ from what consumer ChatGPT, Claude, Gemini or Perplexity
      show, and can vary between runs.
    </p>
  );
}
