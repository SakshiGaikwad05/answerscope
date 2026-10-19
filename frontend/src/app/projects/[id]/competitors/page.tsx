"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { ProviderNotConfigured, RunConditionsNote } from "@/components/ProviderNotice";
import { Badge, Card, EmptyState, ErrorState, Loading, Meter } from "@/components/ui";
import { api, type RunDetail, type RunSummary } from "@/lib/api";
import { CATEGORY_LABELS, METRIC_DEFINITIONS, dateTime, pct } from "@/lib/format";

export default function CompetitorsPage() {
  const { projectId, dashboard } = useProject();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listRuns(projectId)
      .then((r) => {
        const done = r.filter((x) => x.status === "completed");
        setRuns(done);
        setSelected((s) => s ?? done[0]?.id ?? null);
      })
      .catch((e: Error) => setError(e.message));
  }, [projectId, dashboard?.latest_run?.id]);

  useEffect(() => {
    if (!selected) return;
    api.getRun(selected).then(setRun).catch((e: Error) => setError(e.message));
  }, [selected]);

  if (error) return <ErrorState message={error} />;
  if (!dashboard || runs === null) return <Loading />;
  if (runs.length === 0) {
    return (
      <div className="space-y-6">
        <ProviderNotConfigured providers={dashboard.providers} />
        <EmptyState
          title="No completed visibility test yet"
          description="Competitor comparison uses answers from a completed visibility test, so every brand is measured on the same questions under the same conditions."
        />
      </div>
    );
  }
  if (!run || run.id !== selected) return <Loading label="Loading comparison…" />;

  const m = run.metrics;
  const entities = [...m.entities].sort((a, b) => b.answers_mentioning - a.answers_mentioning);
  const tested = run.answers.filter((a) => !a.error);
  const hasCompetitors = m.entities.some((e) => e.entity_type === "competitor");

  return (
    <div className="space-y-6">
      {runs.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="cmp-run" className="text-slate-600">Visibility test</label>
          <select id="cmp-run" value={selected ?? ""} onChange={(e) => setSelected(Number(e.target.value))} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5">
            {runs.map((r) => <option key={r.id} value={r.id}>Run #{r.id} · {dateTime(r.created_at)} · {r.model}</option>)}
          </select>
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="text-sm text-slate-700">
          All numbers below come from the same {m.questions_tested} answers in run #{run.id}, so each brand was measured on identical
          questions, provider and settings. Competitors are the ones tracked when the run started.
        </p>
        <div className="mt-2"><RunConditionsNote conditions={run.conditions} when={dateTime(run.created_at)} /></div>
      </div>

      {!hasCompetitors && (
        <EmptyState
          title="No competitors were tracked in this run"
          description={<>Add competitors in <Link href={`/projects/${projectId}/settings`} className="text-indigo-700 hover:underline">Settings</Link>, then run a new visibility test.</>}
        />
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Mention rate" description="Share of tested answers that name each brand">
          <ul className="space-y-3">
            {entities.map((e) => (
              <li key={e.name}>
                <p className="mb-1 text-sm">
                  <span className={e.entity_type === "brand" ? "font-semibold" : ""}>{e.name}</span>
                  {e.entity_type === "brand" && <Badge tone="accent" className="ml-2">you</Badge>}
                  <span className="ml-2 text-xs text-slate-500">{e.answers_mentioning} of {m.questions_tested}</span>
                </p>
                <Meter value={e.mention_rate} label={`${e.name} mention rate`} emphasize={e.entity_type === "brand"} />
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Citation rate" description="Share of tested answers that cite or link each brand's website">
          <ul className="space-y-3">
            {entities.map((e) => {
              const knowsDomain = e.entity_type === "brand" || run.conditions.competitors?.find((c) => c.name === e.name)?.domain;
              return (
                <li key={e.name}>
                  <p className="mb-1 text-sm">
                    <span className={e.entity_type === "brand" ? "font-semibold" : ""}>{e.name}</span>
                    {e.entity_type === "brand" && <Badge tone="accent" className="ml-2">you</Badge>}
                    {knowsDomain ? <span className="ml-2 text-xs text-slate-500">{e.answers_citing} of {m.questions_tested}</span> : <span className="ml-2 text-xs text-slate-500">no website on file — citations not tracked</span>}
                  </p>
                  {knowsDomain ? <Meter value={e.citation_rate} label={`${e.name} citation rate`} emphasize={e.entity_type === "brand"} /> : null}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>

      <Card title="Comparison table" description={METRIC_DEFINITIONS.shareOfVoice}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <caption className="sr-only">Brand and competitor visibility for run {run.id}</caption>
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-2 font-medium">Brand</th>
                <th className="py-2 text-right font-medium">Answers mentioning</th>
                <th className="py-2 text-right font-medium">Mention rate</th>
                <th className="py-2 text-right font-medium">Answers citing site</th>
                <th className="py-2 text-right font-medium">Citation rate</th>
                <th className="py-2 text-right font-medium">Share of voice</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {entities.map((e) => (
                <tr key={e.name} className={e.entity_type === "brand" ? "bg-indigo-50/50 font-medium" : ""}>
                  <td className="py-2">{e.name}{e.entity_type === "brand" && " (you)"}</td>
                  <td className="py-2 text-right">{e.answers_mentioning}</td>
                  <td className="py-2 text-right">{pct(e.mention_rate)}</td>
                  <td className="py-2 text-right">{e.answers_citing}</td>
                  <td className="py-2 text-right">{pct(e.citation_rate)}</td>
                  <td className="py-2 text-right">{pct(e.share_of_voice)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-sm text-slate-600">
          In <strong>{m.answers_with_competitor_but_not_brand}</strong> answers a competitor was mentioned but {dashboard.project.brand_name} was not.
        </p>
      </Card>

      <Card title="Question by question" description="M = mentioned, C = website cited. Every column is measured on the same answer.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[40rem] text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-2 pr-3 font-medium">Question</th>
                {entities.map((e) => <th key={e.name} className="px-2 py-2 text-center font-medium">{e.name}</th>)}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {tested.map((a) => (
                <tr key={a.id}>
                  <td className="py-2 pr-3">
                    <span className="text-slate-800">{a.question_text}</span>
                    <span className="block text-xs text-slate-500">{CATEGORY_LABELS[a.question_category] ?? a.question_category}</span>
                  </td>
                  {entities.map((e) => {
                    const mentioned = a.mentions.some((x) => x.entity_name === e.name && x.entity_type === e.entity_type && x.kind === "mention");
                    const cited = a.mentions.some((x) => x.entity_name === e.name && x.entity_type === e.entity_type && x.kind === "citation");
                    return (
                      <td key={e.name} className="px-2 py-2 text-center font-mono text-xs">
                        {mentioned || cited ? (
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-800" title={`${e.name}: ${mentioned ? "mentioned" : ""}${mentioned && cited ? ", " : ""}${cited ? "website cited" : ""}`}>
                            {mentioned ? "M" : ""}{cited ? "C" : ""}
                          </span>
                        ) : <span className="text-slate-300" aria-label="not mentioned">·</span>}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
