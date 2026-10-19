"use client";

import { Button } from "@/components/ui";

export interface CompetitorDraft {
  name: string;
  website_url: string;
}

export const MAX_COMPETITORS = 10;

export function CompetitorFields({ value, onChange }: { value: CompetitorDraft[]; onChange: (v: CompetitorDraft[]) => void }) {
  const update = (i: number, patch: Partial<CompetitorDraft>) =>
    onChange(value.map((c, idx) => (idx === i ? { ...c, ...patch } : c)));

  return (
    <fieldset>
      <legend className="text-sm font-medium text-slate-800">
        Competitors <span className="font-normal text-slate-500">(optional, up to {MAX_COMPETITORS})</span>
      </legend>
      <p className="mt-0.5 text-xs text-slate-500">
        Add a website to also detect when AI answers cite that competitor&apos;s site.
      </p>
      <div className="mt-3 space-y-2">
        {value.map((c, i) => (
          <div key={i} className="flex flex-col gap-2 sm:flex-row">
            <label className="sr-only" htmlFor={`comp-name-${i}`}>Competitor {i + 1} name</label>
            <input
              id={`comp-name-${i}`}
              value={c.name}
              onChange={(e) => update(i, { name: e.target.value })}
              placeholder="Competitor name"
              maxLength={200}
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            <label className="sr-only" htmlFor={`comp-url-${i}`}>Competitor {i + 1} website</label>
            <input
              id={`comp-url-${i}`}
              value={c.website_url}
              onChange={(e) => update(i, { website_url: e.target.value })}
              placeholder="competitor.com (optional)"
              className="flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            <Button type="button" variant="ghost" onClick={() => onChange(value.filter((_, idx) => idx !== i))} aria-label={`Remove competitor ${i + 1}`}>
              Remove
            </Button>
          </div>
        ))}
      </div>
      {value.length < MAX_COMPETITORS && (
        <Button type="button" variant="secondary" className="mt-3" onClick={() => onChange([...value, { name: "", website_url: "" }])}>
          + Add competitor
        </Button>
      )}
    </fieldset>
  );
}

export function cleanCompetitors(value: CompetitorDraft[]) {
  return value
    .filter((c) => c.name.trim())
    .map((c) => ({ name: c.name.trim(), website_url: c.website_url.trim() || undefined }));
}
