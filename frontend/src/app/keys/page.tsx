"use client";

import { useCallback, useEffect, useState } from "react";

import { Badge, Button, Card, ErrorState, Loading } from "@/components/ui";
import { api, type KeysStatus, type UserKey } from "@/lib/api";
import { dateTime } from "@/lib/format";

const ASSISTANTS = ["openai", "anthropic", "gemini", "perplexity"];

function KeyStatus({ k }: { k: UserKey }) {
  if (k.needs_reentry) return <Badge tone="warning">Re-enter needed</Badge>;
  if (k.saved && k.verified) return <Badge tone="good"><span aria-hidden="true">✓</span> Connected ····{k.last4}</Badge>;
  if (k.saved) return <Badge tone="accent">Saved ····{k.last4} · checked on first use</Badge>;
  if (k.server_key_available) return <Badge tone="neutral">Using the server&apos;s key</Badge>;
  return <Badge tone="neutral">Not connected</Badge>;
}

function KeyRow({ k, enabled, onChange }: { k: UserKey; enabled: boolean; onChange: (s: KeysStatus | null) => void }) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<"save" | "remove" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const inputId = `key-${k.provider}`;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return;
    setBusy("save");
    setMessage(null);
    try {
      const status = await api.saveKey(k.provider, value);
      setValue("");
      const saved = status.keys.find((x) => x.provider === k.provider);
      setMessage({ ok: true, text: saved?.verified ? "Key works and is saved." : "Saved. This provider can't be checked for free, so it's checked on first use." });
      onChange(status);
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function remove() {
    setBusy("remove");
    setMessage(null);
    try {
      await api.deleteKey(k.provider);
      onChange(null);
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="py-5 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <label htmlFor={inputId} className="font-semibold text-slate-900">{k.label}</label>
            <KeyStatus k={k} />
          </div>
          <p className="mt-1 text-sm text-slate-600">{k.purpose}</p>
          {k.saved && k.updated_at && <p className="mt-1 text-xs text-slate-400">Updated {dateTime(k.updated_at)}</p>}
        </div>
        <a href={k.get_key_url} target="_blank" rel="noopener noreferrer" className="text-sm font-medium text-indigo-700 hover:underline">
          Get a key <span aria-hidden="true">↗</span>
        </a>
      </div>
      {enabled && (
        <form onSubmit={save} className="mt-3 flex flex-wrap gap-2">
          <input
            id={inputId}
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={k.saved ? "Paste a new key to replace it" : "Paste your API key"}
            autoComplete="off"
            spellCheck={false}
            maxLength={400}
            className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 font-mono text-sm"
          />
          <Button type="submit" loading={busy === "save"} disabled={!value.trim() || busy !== null}>
            {k.saved ? "Replace" : "Save & check"}
          </Button>
          {(k.saved || k.needs_reentry) && (
            <Button type="button" variant="ghost" loading={busy === "remove"} disabled={busy !== null} onClick={remove}>
              Remove
            </Button>
          )}
        </form>
      )}
      {message && (
        <p role={message.ok ? "status" : "alert"} className={`mt-2 text-sm ${message.ok ? "text-emerald-700" : "text-rose-700"}`}>
          {message.text}
        </p>
      )}
    </li>
  );
}

export default function KeysPage() {
  const [status, setStatus] = useState<KeysStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api.keys().then((s) => { setStatus(s); setError(null); }).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => { load(); }, [load]);

  const onChange = (s: KeysStatus | null) => (s ? setStatus(s) : load());

  return (
    <div className="mx-auto max-w-3xl space-y-6 px-4 py-10 sm:px-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">API keys</h1>
        <p className="mt-1 text-sm text-slate-600">
          Connect the AI assistants you want to test. Each test runs on your own key, so you control the cost. The website
          audit, local SEO checks and action plan are free and don&apos;t need any key.
        </p>
      </div>

      {error ? (
        <ErrorState message={error} onRetry={load} />
      ) : status === null ? (
        <Loading label="Loading keys…" />
      ) : (
        <>
          {!status.enabled && (
            <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              Saving personal API keys is turned off on this server. The server admin must set <code className="font-mono">AEO_SECRETS_KEY</code>.
            </div>
          )}
          <div className="rounded-xl border border-indigo-100 bg-accent-soft p-4 text-sm text-indigo-950">
            <p className="font-semibold">Where to start</p>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <li><span className="font-medium">Free:</span> Google Gemini keys from AI Studio include a free daily allowance.</li>
              <li><span className="font-medium">Paid:</span> a test sends up to 20 questions, each with web search, so the cost depends on your provider&apos;s pricing. Set a spending limit in their dashboard first.</li>
              <li>Results come from each provider&apos;s API, which can differ from what the ChatGPT, Claude, Gemini or Perplexity apps show.</li>
            </ul>
          </div>

          <Card title="AI assistants" description="Your business's visibility is measured in the answers from these.">
            <ul className="divide-y divide-slate-100">
              {status.keys.filter((k) => ASSISTANTS.includes(k.provider)).map((k) => (
                <KeyRow key={k.provider} k={k} enabled={status.enabled} onChange={onChange} />
              ))}
            </ul>
          </Card>
          <Card title="Analysis & search (optional)" description="Better questions, recommended-business extraction and backlink discovery.">
            <ul className="divide-y divide-slate-100">
              {status.keys.filter((k) => !ASSISTANTS.includes(k.provider)).map((k) => (
                <KeyRow key={k.provider} k={k} enabled={status.enabled} onChange={onChange} />
              ))}
            </ul>
          </Card>

          <section aria-labelledby="key-safety" className="rounded-xl border border-slate-200 bg-white p-5 text-sm text-slate-600">
            <h2 id="key-safety" className="font-semibold text-slate-900">How your keys are handled</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Encrypted before they&apos;re stored, and only ever used on the server for your own tests.</li>
              <li>Never shown again after saving: you&apos;ll only see the last 4 characters.</li>
              <li>When you save a key, it is checked with a free request where the provider allows it.</li>
              <li>Remove a key here at any time, and set a spending limit in your provider&apos;s dashboard.</li>
            </ul>
          </section>
        </>
      )}
    </div>
  );
}
