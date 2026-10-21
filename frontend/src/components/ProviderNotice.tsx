import Link from "next/link";

import type { ProviderStatus, RunConditions } from "@/lib/api";

export function ProviderNotConfigured({ providers }: { providers: ProviderStatus[] }) {
  if (providers.some((p) => p.configured)) return null;
  return (
    <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-indigo-100 bg-accent-soft p-4 text-sm text-indigo-950">
      <div className="min-w-0 flex-1">
        <p className="font-semibold">Connect an AI assistant to test your visibility</p>
        <p className="mt-0.5 text-indigo-900/80">
          Add your own ChatGPT, Claude, Gemini or Perplexity API key. Nothing is simulated without one. The website audit,
          local SEO checks and action plan work without any key.
        </p>
      </div>
      <Link href="/keys" className="rounded-lg bg-accent px-4 py-2 font-medium text-white hover:bg-accent-hover">Add API keys</Link>
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
