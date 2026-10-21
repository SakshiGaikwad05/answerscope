"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, StatusBadge, cx } from "@/components/ui";
import { api, type CompareMetric, type RunComparison, type RunSummary } from "@/lib/api";
import { dateTime, isActive, pct } from "@/lib/format";

function Delta({ value, answers, noise }: { value: number | null; answers?: number | null; noise?: boolean }) {
  if (value === null) return <span className="text-slate-400">n/a</span>;
  const up = value > 0, down = value < 0;
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={cx("font-semibold tabular-nums", up && "text-emerald-700", down && "text-rose-700", !up && !down && "text-slate-500")}>
        <span aria-hidden="true">{up ? "▲" : down ? "▼" : "–"} </span>
        {up ? "+" : ""}{value} pts
      </span>
      {answers != null && answers > 0 && <span className="text-xs text-slate-500">({answers} answer{answers === 1 ? "" : "s"})</span>}
      {noise && value !== 0 && <Badge tone="neutral">may be normal variation</Badge>}
    </span>
  );
}

function MetricCard({ m }: { m: CompareMetric }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-sm font-medium text-slate-600">{m.label}</p>
      <p className="mt-2 text-lg tabular-nums text-slate-900">
        {pct(m.base)} <span aria-hidden="true" className="text-slate-400">→</span><span className="sr-only">to</span>{" "}
        <span className="text-2xl font-semibold">{pct(m.target)}</span>
      </p>
      <div className="mt-1 text-sm"><Delta value={m.delta_pts} answers={m.answers_changed} noise={m.may_be_noise} /></div>
    </div>
  );
}

const CHANGE_GROUPS: { key: keyof RunComparison["question_changes"]; label: string; good: boolean }[] = [
  { key: "gained_mention", label: "Now mentions you", good: true },
  { key: "now_known", label: "AI now knows your brand", good: true },
  { key: "gained_citation", label: "Now cites your website", good: true },
  { key: "lost_mention", label: "No longer mentions you", good: false },
  { key: "now_unknown", label: "AI now says it can't find you", good: false },
  { key: "lost_citation", label: "No longer cites your website", good: false },
];

export default function ComparePage() {
  const { projectId, dashboard, refresh } = useProject();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [baseId, setBaseId] = useState<number | null>(null);
  const [targetId, setTargetId] = useState<number | null>(null);
  const [result, setResult] = useState<RunComparison | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retesting, setRetesting] = useState(false);
  const [notice, setNotice] = useState<{ tone: "info" | "error"; text: string } | null>(null);
  const [assistantFilter, setAssistantFilter] = useState<string | null>(null);

  const latestJob = dashboard?.recent_runs[0];
  const latestStatus = latestJob?.status;

  useEffect(() => {
    api.listRuns(projectId).then(setRuns).catch((e: Error) => setError(e.message));
  }, [projectId, latestStatus, latestJob?.id]);

  const allCompleted = useMemo(() => (runs ?? []).filter((r) => r.status === "completed"), [runs]);
  const testedProviders = useMemo(() => [...new Set(allCompleted.map((r) => r.provider))], [allCompleted]);
  // Compare within one assistant: ChatGPT vs ChatGPT, Claude vs Claude, ...
  const provider = assistantFilter ?? testedProviders[0] ?? null;
  const completed = useMemo(() => allCompleted.filter((r) => r.provider === provider), [allCompleted, provider]);
  const assistantName = (name: string) => dashboard?.providers.find((p) => p.name === name)?.assistant || name;

  // Default: latest completed run vs the run it retested (or the previous completed run).
  const target = targetId ?? completed[0]?.id ?? null;
  const targetRun = completed.find((r) => r.id === target);
  const retestOf = targetRun?.conditions.retest_of as number | undefined;
  const base =
    baseId ?? (retestOf && completed.some((r) => r.id === retestOf) ? retestOf : completed.find((r) => r.id !== target)?.id ?? null);

  useEffect(() => {
    if (!base || !target || base === target) return;
    let cancelled = false;
    api
      .compareRuns(projectId, base, target)
      .then((r) => !cancelled && (setResult(r), setError(null)))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [projectId, base, target]);

  async function retest() {
    if (!completed[0]) return;
    setRetesting(true);
    setNotice(null);
    try {
      const run = await api.retestRun(completed[0].id);
      setNotice({ tone: "info", text: `Retest started (run #${run.id}). It asks the same ${run.total_questions} questions; results appear here when it finishes.` });
      setTargetId(null);
      setBaseId(null);
      await refresh();
    } catch (e) {
      setNotice({ tone: "error", text: (e as Error).message });
    } finally {
      setRetesting(false);
    }
  }

  if (error && !result) return <ErrorState message={error} />;
  if (!dashboard || runs === null) return <Loading />;

  const running = latestJob && isActive(latestJob.status);
  const quotaLeft = dashboard.usage?.visibility_run.remaining;
  const retestBox = (
    <Card
      title="Retest and measure"
      description="After you make changes, ask the AI the exact same questions again and compare the results."
    >
      <div className="flex flex-wrap items-center gap-3">
        {testedProviders.length > 1 && (
          <label className="flex items-center gap-2">
            <span className="text-slate-600">Assistant</span>
            <select value={provider ?? ""} onChange={(e) => { setAssistantFilter(e.target.value); setBaseId(null); setTargetId(null); }}
                    className="rounded-lg border border-slate-300 bg-white px-2 py-1.5">
              {testedProviders.map((p) => <option key={p} value={p}>{assistantName(p)}</option>)}
            </select>
          </label>
        )}
        <Button onClick={retest} loading={retesting || !!running} disabled={!completed[0] || quotaLeft === 0}>
          {running ? "Test running…" : completed[0] ? `Retest the questions from run #${completed[0].id}` : "Retest"}
        </Button>
        <span className="text-sm text-slate-500">
          Uses 1 visibility test{quotaLeft != null && ` (${quotaLeft} left today)`}. Tip: wait until search engines have re-crawled your changes,
          which can take days to weeks.
        </span>
      </div>
      {running && latestJob && (
        <p role="status" className="mt-3 flex items-center gap-2 text-sm text-indigo-900">
          <StatusBadge status={latestJob.status} /> {latestJob.completed_questions} of {latestJob.total_questions} questions answered…
        </p>
      )}
      {notice && (
        <p role={notice.tone === "error" ? "alert" : "status"} className={cx("mt-3 rounded-lg px-3 py-2 text-sm", notice.tone === "error" ? "bg-rose-50 text-rose-800" : "bg-indigo-50 text-indigo-900")}>
          {notice.text}
        </p>
      )}
    </Card>
  );

  if (completed.length < 2) {
    return (
      <div className="space-y-6">
        {completed.length === 1 && retestBox}
        <EmptyState
          title={completed.length === 0 ? "No completed visibility test yet" : "One more test needed to compare"}
          description={
            completed.length === 0 ? (
              <>Run a visibility test from the <Link href={`/projects/${projectId}`} className="text-indigo-700 hover:underline">Dashboard</Link> first.</>
            ) : (
              "Make changes from your Action plan, then retest to see what changed."
            )
          }
        />
      </div>
    );
  }

  const runLabel = (r: RunSummary) =>
    `Run #${r.id} · ${dateTime(r.created_at)} · ${r.model}${r.conditions.retest_of ? ` · retest of #${r.conditions.retest_of}` : ""}`;

  return (
    <div className="space-y-6">
      {retestBox}

      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-slate-600">Before</span>
          <select value={base ?? ""} onChange={(e) => setBaseId(Number(e.target.value))} className="max-w-xs rounded-lg border border-slate-300 bg-white px-2 py-1.5">
            {completed.map((r) => <option key={r.id} value={r.id} disabled={r.id === target}>{runLabel(r)}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-slate-600">After</span>
          <select value={target ?? ""} onChange={(e) => setTargetId(Number(e.target.value))} className="max-w-xs rounded-lg border border-slate-300 bg-white px-2 py-1.5">
            {completed.map((r) => <option key={r.id} value={r.id} disabled={r.id === base}>{runLabel(r)}</option>)}
          </select>
        </label>
      </div>

      {!result || result.base.id !== base || result.target.id !== target ? (
        <Loading label="Comparing…" />
      ) : (
        <>
          {!result.comparable && (
            <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              <p className="font-semibold"><span aria-hidden="true">⚠ </span>These runs weren&apos;t measured under the same conditions</p>
              <ul className="mt-1 list-disc pl-5">{result.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
              <p className="mt-1">Differences below may come from these changes rather than from your website.</p>
            </div>
          )}
          <p className="text-sm text-slate-600">
            Compared on the <strong>{result.questions_compared}</strong> questions both runs answered
            {(result.questions_only_in_base > 0 || result.questions_only_in_target > 0) &&
              ` (${result.questions_only_in_base + result.questions_only_in_target} asked in only one run are excluded)`}
            . {result.one_answer_pts != null && <>One answer = {result.one_answer_pts} percentage points.</>}
          </p>

          <section aria-labelledby="cmp-metrics" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <h2 id="cmp-metrics" className="sr-only">Metric changes</h2>
            {result.metrics.map((m) => <MetricCard key={m.key} m={m} />)}
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="What changed, question by question" description={`${result.unchanged_questions} of ${result.questions_compared} questions had no change.`}>
              <div className="space-y-4">
                {CHANGE_GROUPS.filter((g) => result.question_changes[g.key].length > 0).map((g) => (
                  <div key={g.key}>
                    <p className={cx("text-sm font-semibold", g.good ? "text-emerald-800" : "text-rose-800")}>
                      <span aria-hidden="true">{g.good ? "▲ " : "▼ "}</span>{g.label} ({result.question_changes[g.key].length})
                    </p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
                      {result.question_changes[g.key].slice(0, 8).map((q) => <li key={q}>{q}</li>)}
                      {result.question_changes[g.key].length > 8 && <li className="text-slate-500">…and {result.question_changes[g.key].length - 8} more</li>}
                    </ul>
                  </div>
                ))}
                {result.competitor_changes.length > 0 && (
                  <div>
                    <p className="text-sm font-semibold text-slate-800">Competitor mentions changed ({result.competitor_changes.length})</p>
                    <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-slate-700">
                      {result.competitor_changes.slice(0, 8).map((c) => (
                        <li key={c.question}>
                          {c.question}
                          {c.gained.length > 0 && <span className="text-slate-500"> · now mentions {c.gained.join(", ")}</span>}
                          {c.lost.length > 0 && <span className="text-slate-500"> · no longer mentions {c.lost.join(", ")}</span>}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {CHANGE_GROUPS.every((g) => result.question_changes[g.key].length === 0) && result.competitor_changes.length === 0 && (
                  <p className="text-sm text-slate-500">No answer changed between these runs.</p>
                )}
              </div>
            </Card>

            <div className="space-y-6">
              <Card title="Brands" description="Mention rate on the shared questions">
                <table className="w-full text-sm">
                  <caption className="sr-only">Mention rate per brand, before and after</caption>
                  <thead>
                    <tr className="border-b border-slate-200 text-left text-slate-500">
                      <th className="py-2 font-medium">Brand</th>
                      <th className="py-2 text-right font-medium">Before</th>
                      <th className="py-2 text-right font-medium">After</th>
                      <th className="py-2 text-right font-medium">Change</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 tabular-nums">
                    {result.entities.map((e) => (
                      <tr key={e.name} className={e.entity_type === "brand" ? "font-medium" : ""}>
                        <td className="py-2">{e.name}{e.entity_type === "brand" && " (you)"}</td>
                        <td className="py-2 text-right">{pct(e.base_mention_rate)}</td>
                        <td className="py-2 text-right">{pct(e.target_mention_rate)}</td>
                        <td className="py-2 text-right"><Delta value={e.delta_pts} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>

              <Card title="Fixes detected between these runs" description="Action items that a re-audit stopped detecting in this period">
                {result.resolved_between.length === 0 ? (
                  <p className="text-sm text-slate-500">None. Re-run the website audit after making changes so fixes are detected.</p>
                ) : (
                  <ul className="space-y-1.5 text-sm">
                    {result.resolved_between.map((r) => (
                      <li key={r.id} className="flex gap-2">
                        <span aria-hidden="true" className="text-emerald-700">✓</span>
                        <span>{r.issue} <span className="text-xs text-slate-500">· {dateTime(r.resolved_at)}</span></span>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            </div>
          </div>

          <p className="text-xs leading-relaxed text-slate-500">
            This shows what changed, not why. Your website changes, updates to the AI model or its search index, and normal
            run-to-run variation can all change answers, so look for changes that hold up across several retests.
          </p>
        </>
      )}
    </div>
  );
}
