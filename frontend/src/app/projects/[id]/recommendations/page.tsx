"use client";

import { useEffect, useState } from "react";

import { FixPanel } from "@/components/FixPanel";
import { useProject } from "@/components/ProjectContext";
import { Badge, Button, EmptyState, ErrorState, Loading, cx } from "@/components/ui";
import { api, type Level, type RecStatus, type Recommendation } from "@/lib/api";
import { dateTime } from "@/lib/format";

const CATEGORY_NAMES: Record<string, string> = {
  visibility: "AI visibility",
  competitors: "Competitors",
  citations: "Citations",
  consistency: "Factual consistency",
  content: "Content",
  metadata: "Metadata",
  structure: "Structure",
  structured_data: "Structured data",
  crawlability: "Crawlability",
  data_quality: "Data quality",
};

const STATUS_LABELS: Record<RecStatus, string> = {
  open: "Open",
  planned: "Planned",
  in_progress: "In progress",
  completed: "Completed",
  dismissed: "Dismissed",
};

type View = "todo" | "completed" | "resolved" | "dismissed" | "all";

const VIEWS: { id: View; label: string; test: (r: Recommendation) => boolean }[] = [
  { id: "todo", label: "To do", test: (r) => r.detected && ["open", "planned", "in_progress"].includes(r.status) },
  { id: "completed", label: "Completed", test: (r) => r.status === "completed" },
  { id: "resolved", label: "No longer detected", test: (r) => !r.detected && !["completed", "dismissed"].includes(r.status) },
  { id: "dismissed", label: "Dismissed", test: (r) => r.status === "dismissed" },
  { id: "all", label: "All", test: () => true },
];

function LevelBadge({ label, level, invert }: { label: string; level: Level; invert?: boolean }) {
  // For impact/confidence "high" is good to act on; for effort "low" is good.
  const strong = invert ? level === "low" : level === "high";
  return (
    <Badge tone={strong ? "accent" : "neutral"}>
      {level} {label}
    </Badge>
  );
}

/** Marked completed, yet a check run after that still found the issue. */
function stillDetectedAfterCompletion(r: Recommendation): boolean {
  return (
    r.status === "completed" &&
    r.detected &&
    !!r.status_updated_at &&
    new Date(r.last_detected_at).getTime() > new Date(r.status_updated_at).getTime()
  );
}

function ActionItem({ rec, onChange }: { rec: Recommendation; onChange: (r: Recommendation) => void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState(rec.note ?? "");

  async function save(body: { status?: RecStatus; note?: string | null }) {
    setSaving(true);
    setError(null);
    try {
      onChange(await api.updateRecommendation(rec.id, body));
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  const source = rec.run_id ? `visibility test #${rec.run_id}` : rec.audit_id ? `audit #${rec.audit_id}` : "latest data";

  return (
    <li className={cx("rounded-xl border bg-white p-5 shadow-sm", rec.blocking && rec.detected ? "border-rose-300" : "border-slate-200")}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          {rec.blocking && rec.detected && <Badge tone="bad">⚑ Do first: blocks other fixes</Badge>}
          <LevelBadge label="impact" level={rec.priority} />
          <LevelBadge label="effort" level={rec.effort} invert />
          <LevelBadge label="confidence" level={rec.confidence} />
          <Badge>{CATEGORY_NAMES[rec.category] ?? rec.category}</Badge>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-600">Status</span>
          <select
            value={rec.status}
            disabled={saving}
            onChange={(e) => void save({ status: e.target.value as RecStatus })}
            className="rounded-lg border border-slate-300 bg-white px-2 py-1"
            aria-label={`Status for: ${rec.issue}`}
          >
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </label>
      </div>

      {stillDetectedAfterCompletion(rec) && (
        <p role="status" className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span aria-hidden="true">⚠ </span>Marked completed on {dateTime(rec.status_updated_at)}, but the {source} run after that still detects this issue.
        </p>
      )}
      {!rec.detected && (
        <p role="status" className="mt-3 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
          <span aria-hidden="true">✓ </span>No longer detected since {dateTime(rec.resolved_at)}.
          {rec.status !== "completed" && rec.status !== "dismissed" && " You can mark it completed."}
        </p>
      )}

      <h2 className="mt-3 font-semibold text-slate-900">{rec.issue}</h2>
      <dl className="mt-3 space-y-3 text-sm">
        <div>
          <dt className="font-medium text-slate-700">Why it matters</dt>
          <dd className="text-slate-600">{rec.why_it_matters}</dd>
        </div>
        <div>
          <dt className="font-medium text-slate-700">What to change</dt>
          <dd className="text-slate-600">{rec.action}</dd>
        </div>
        {rec.verify && (
          <div>
            <dt className="font-medium text-slate-700">How to verify</dt>
            <dd className="text-slate-600">{rec.verify}</dd>
          </div>
        )}
        {rec.evidence.length > 0 && (
          <div>
            <dt className="font-medium text-slate-700">What we found (from {source})</dt>
            <dd>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-600">
                {rec.evidence.map((e, i) => <li key={i} className="break-words">{e}</li>)}
              </ul>
            </dd>
          </div>
        )}
      </dl>

      <FixPanel rec={rec} />

      <div className="mt-4 border-t border-slate-100 pt-3 text-sm">
        {noteOpen ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              if (await save({ note })) setNoteOpen(false);
            }}
            className="space-y-2"
          >
            <label htmlFor={`note-${rec.id}`} className="font-medium text-slate-700">Note</label>
            <textarea
              id={`note-${rec.id}`}
              value={note}
              maxLength={2000}
              rows={3}
              onChange={(e) => setNote(e.target.value)}
              className="w-full rounded-lg border border-slate-300 px-3 py-2"
            />
            <div className="flex gap-2">
              <Button type="submit" loading={saving}>Save note</Button>
              <Button type="button" variant="ghost" onClick={() => { setNote(rec.note ?? ""); setNoteOpen(false); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <div className="flex flex-wrap items-center justify-between gap-2 text-slate-500">
            <span>
              {rec.note ? <span className="text-slate-700">Note: {rec.note}</span> : "No note"}
            </span>
            <span className="flex items-center gap-3">
              <span className="text-xs">First found {dateTime(rec.first_detected_at)}</span>
              <button onClick={() => setNoteOpen(true)} className="font-medium text-indigo-700 hover:underline">
                {rec.note ? "Edit note" : "Add note"}
              </button>
            </span>
          </div>
        )}
        {error && <p role="alert" className="mt-2 text-rose-700">{error}</p>}
      </div>
    </li>
  );
}

export default function ActionPlanPage() {
  const { projectId, dashboard, refresh } = useProject();
  const [recs, setRecs] = useState<Recommendation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>("todo");

  useEffect(() => {
    api.recommendations(projectId).then(setRecs).catch((e: Error) => setError(e.message));
  }, [projectId, dashboard?.latest_audit?.id, dashboard?.latest_run?.id]);

  if (error) return <ErrorState message={error} />;
  if (recs === null) return <Loading label="Loading action plan…" />;
  if (recs.length === 0) {
    return (
      <EmptyState
        title="No action items yet"
        description="Items are created from evidence: run the website audit (and, if configured, a visibility test) first."
      />
    );
  }

  const counts = Object.fromEntries(VIEWS.map((v) => [v.id, recs.filter(v.test).length])) as Record<View, number>;
  const shown = recs.filter(VIEWS.find((v) => v.id === view)!.test);
  const done = counts.completed + counts.resolved;

  function update(r: Recommendation) {
    setRecs((prev) => prev && prev.map((x) => (x.id === r.id ? r : x)));
    void refresh(); // keep dashboard counts in sync
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-slate-200 bg-white p-4 text-sm text-slate-600">
        <p>
          <span className="font-semibold text-slate-900">{counts.todo} to do</span> · {done} done or no longer detected · {counts.dismissed} dismissed.
          Ordered by what to do first: blocking root causes, then the best ratio of impact and confidence to effort.
        </p>
        <p className="mt-1">
          Items keep their status across re-audits. When a re-audit or re-test no longer finds an issue it moves to
          &ldquo;No longer detected&rdquo;. Fixes improve how clearly your site answers questions, but no change can guarantee AI mentions or citations.
        </p>
      </div>

      <div role="tablist" aria-label="Action plan views" className="flex flex-wrap gap-2">
        {VIEWS.map((v) => (
          <button
            key={v.id}
            role="tab"
            aria-selected={view === v.id}
            onClick={() => setView(v.id)}
            className={cx(
              "rounded-full border px-3 py-1 text-sm",
              view === v.id ? "border-accent bg-accent-soft text-indigo-800" : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50",
            )}
          >
            {v.label} ({counts[v.id]})
          </button>
        ))}
      </div>

      {shown.length === 0 ? (
        <EmptyState
          title={view === "todo" ? "Nothing left to do" : "Nothing here"}
          description={view === "todo" ? "Re-run the audit and visibility test to confirm your fixes." : undefined}
        />
      ) : (
        <ol className="space-y-4">
          {shown.map((r) => <ActionItem key={r.id} rec={r} onChange={update} />)}
        </ol>
      )}
    </div>
  );
}
