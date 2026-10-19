"use client";

import { useEffect, useState } from "react";

import { Badge, Button } from "@/components/ui";
import { api, type FixDraft, type Recommendation } from "@/lib/api";
import { dateTime, shortUrl } from "@/lib/format";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          /* clipboard unavailable (e.g. insecure origin); the text can still be selected */
        }
      }}
      className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function Draft({ draft }: { draft: FixDraft }) {
  const isTemplate = draft.generator === "template";
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium text-slate-900">{draft.title}</p>
          {isTemplate ? (
            <Badge tone="good">Generated from your data</Badge>
          ) : (
            <Badge tone="warning">AI draft ({draft.generator}): review before publishing</Badge>
          )}
        </div>
        <span className="text-xs text-slate-500">{dateTime(draft.created_at)}</span>
      </div>
      {draft.placeholders.length > 0 && (
        <div className="mt-3 rounded-md bg-amber-50 p-2 text-sm text-amber-900">
          <p className="font-medium">Fill in before publishing ({draft.placeholders.length})</p>
          <ul className="mt-1 list-disc pl-5">
            {draft.placeholders.slice(0, 12).map((p, i) => <li key={i}>{p}</li>)}
          </ul>
        </div>
      )}
      <div className="mt-3">
        <div className="mb-1 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{draft.format}</span>
          <CopyButton text={draft.content} />
        </div>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-words rounded-md border border-slate-200 bg-white p-3 font-mono text-xs leading-relaxed text-slate-800">
          {draft.content}
        </pre>
      </div>
      {draft.notes && <p className="mt-3 whitespace-pre-wrap text-sm text-slate-700">{draft.notes}</p>}
      {draft.sources.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">Based on: {draft.sources.map(shortUrl).join(", ")}</p>
      )}
    </div>
  );
}

export function FixPanel({ rec }: { rec: Recommendation }) {
  const [open, setOpen] = useState(false);
  const [drafts, setDrafts] = useState<FixDraft[] | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || drafts !== null) return;
    api.listFixes(rec.id).then(setDrafts).catch((e: Error) => setError(e.message));
  }, [open, drafts, rec.id]);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const draft = await api.createFix(rec.id);
      setDrafts((prev) => [draft, ...(prev ?? [])]);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  if (!rec.fix_available) return null;

  return (
    <div className="mt-4 border-t border-slate-100 pt-3">
      {!open ? (
        <Button variant="secondary" onClick={() => setOpen(true)}>Draft a fix</Button>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={generate} loading={generating}>
              {generating ? "Writing draft… (up to a minute)" : drafts && drafts.length ? "Generate a new draft" : "Generate draft"}
            </Button>
            <p className="text-xs text-slate-500">
              Drafts use only content found on your pages. Unknown facts become [ADD: …] placeholders. Nothing is changed on your site.
            </p>
          </div>
          {error && <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>}
          {drafts === null && !error && <p className="text-sm text-slate-500">Loading drafts…</p>}
          {drafts?.slice(0, 3).map((d) => <Draft key={d.id} draft={d} />)}
        </div>
      )}
    </div>
  );
}
