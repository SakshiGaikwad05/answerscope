"use client";

import Link from "next/link";
import { useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { OverviewPanel } from "@/components/OverviewPanel";
import { ProviderNotConfigured } from "@/components/ProviderNotice";
import { Button, Card, StatusBadge } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, isActive } from "@/lib/format";

function Step({ n, title, children, action }: { n: number; title: string; children: React.ReactNode; action: React.ReactNode }) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-slate-200 p-4 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex gap-3">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-indigo-700">{n}</span>
        <div>
          <p className="font-medium text-slate-900">{title}</p>
          <div className="text-sm text-slate-500">{children}</div>
        </div>
      </div>
      <div className="shrink-0">{action}</div>
    </li>
  );
}

export default function DashboardPage() {
  const { dashboard, refresh, projectId } = useProject();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "info"; text: string; setup?: string } | null>(null);
  if (!dashboard) return null;

  const latestAuditJob = dashboard.recent_audits[0];
  const latestRunJob = dashboard.recent_runs[0];
  const auditRunning = isActive(latestAuditJob?.status);
  const runRunning = isActive(latestRunJob?.status);
  const configured = dashboard.providers.some((p) => p.configured);
  const configuredAssistants = dashboard.providers.filter((p) => p.configured).map((p) => p.assistant || p.display_name);
  const runsAvailable = dashboard.usage?.visibility_run.remaining ?? Infinity;
  const metrics = dashboard.latest_run_metrics;
  const audit = dashboard.latest_audit;

  async function act(key: string, fn: () => Promise<unknown>, success?: (r: unknown) => string | null) {
    setBusy(key);
    setMessage(null);
    try {
      const r = await fn();
      const text = success?.(r);
      if (text) setMessage({ tone: "info", text });
      await refresh();
    } catch (e) {
      const err = e as ApiError;
      setMessage({ tone: "error", text: err.message, setup: err.setup });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-6">
      <ProviderNotConfigured providers={dashboard.providers} />

      <Card title="Workflow" description="Run these steps in order. Results are saved so you can revisit them in History.">
        <ol className="space-y-3">
          <Step
            n={1}
            title="Website audit"
            action={
              <Button loading={busy === "audit" || auditRunning} onClick={() => act("audit", () => api.startAudit(projectId))}>
                {auditRunning ? "Auditing…" : audit ? "Re-run audit" : "Run audit"}
              </Button>
            }
          >
            {latestAuditJob ? (
              <span className="flex flex-wrap items-center gap-2">
                <StatusBadge status={latestAuditJob.status} />
                {isActive(latestAuditJob.status) && <span>{latestAuditJob.progress_message}</span>}
                {latestAuditJob.status === "failed" && <span className="text-rose-700">{latestAuditJob.error}</span>}
                {latestAuditJob.status === "completed" && <span>{latestAuditJob.pages_crawled} pages crawled · {dateTime(latestAuditJob.completed_at)}</span>}
              </span>
            ) : (
              "Crawls your site and checks metadata, structure, schema, FAQ content and crawler access."
            )}
          </Step>
          <Step
            n={2}
            title="Generate customer questions"
            action={
              <Button
                variant={dashboard.active_question_count ? "secondary" : "primary"}
                loading={busy === "questions"}
                onClick={() =>
                  act("questions", () => api.generateQuestions(projectId), (r) => {
                    const res = r as { questions: unknown[]; source: string; note: string | null };
                    const src = res.source === "llm" ? "by the AI provider" : res.source === "template" ? "from templates" : "by the AI provider and templates";
                    return `Generated ${res.questions.length} questions ${src}.${res.note ? " " + res.note : ""}`;
                  })
                }
              >
                {dashboard.active_question_count ? "Regenerate" : "Generate questions"}
              </Button>
            }
          >
            {dashboard.active_question_count ? (
              <span>
                {dashboard.active_question_count} questions ready · <Link className="text-indigo-700 hover:underline" href={`/projects/${projectId}/results`}>view</Link>
              </span>
            ) : (
              "20 questions customers might ask AI about your brand and category."
            )}
          </Step>
          <Step
            n={3}
            title="AI visibility test (all configured assistants)"
            action={
              <Button
                loading={busy === "run" || runRunning}
                disabled={!configured || !dashboard.active_question_count || runsAvailable < configuredAssistants.length}
                onClick={() =>
                  act("run", () => api.startMultiRun(projectId), (r) => {
                    const runs = r as { provider: string }[];
                    return `Started ${runs.length} test${runs.length === 1 ? "" : "s"}: ${configuredAssistants.join(", ")}. Each assistant gets the same questions.`;
                  })
                }
                title={
                  !configured
                    ? "Configure an AI provider API key first"
                    : !dashboard.active_question_count
                      ? "Generate questions first"
                      : runsAvailable < configuredAssistants.length
                        ? `Needs ${configuredAssistants.length} visibility tests; ${runsAvailable} left today`
                        : undefined
                }
              >
                {runRunning ? "Testing…" : `Test ${configuredAssistants.length || ""} assistant${configuredAssistants.length === 1 ? "" : "s"}`}
              </Button>
            }
          >
            {!configured ? (
              <>Needs at least one assistant API key (ChatGPT, Claude, Gemini or Perplexity). <Link href="/keys" className="font-medium text-indigo-700 hover:underline">Add API keys</Link></>
            ) : latestRunJob ? (
              <span className="flex flex-wrap items-center gap-2">
                <StatusBadge status={latestRunJob.status} />
                {isActive(latestRunJob.status) && (
                  <span>
                    {latestRunJob.completed_questions} of {latestRunJob.total_questions} questions processed
                  </span>
                )}
                {latestRunJob.status === "failed" && <span className="text-rose-700">{latestRunJob.error}</span>}
                {latestRunJob.status === "completed" && <span>{latestRunJob.model} · {dateTime(latestRunJob.completed_at)}</span>}
              </span>
            ) : (
              `Asks each question to ${configuredAssistants.join(", ")} and records mentions, citations, list position and competitors.`
            )}
          </Step>
        </ol>
        {dashboard.usage && configured && (
          <p className="mt-4 text-xs text-slate-500">
            AI usage in the last 24 hours: visibility tests {dashboard.usage.visibility_run.used}/{dashboard.usage.visibility_run.limit} ·
            question generation {dashboard.usage.question_generation.used}/{dashboard.usage.question_generation.limit} ·
            fix drafts {dashboard.usage.fix_generation.used}/{dashboard.usage.fix_generation.limit}
          </p>
        )}
        {message && (
          <div
            role={message.tone === "error" ? "alert" : "status"}
            className={`mt-4 rounded-lg px-3 py-2 text-sm ${message.tone === "error" ? "bg-rose-50 text-rose-800" : "bg-indigo-50 text-indigo-900"}`}
          >
            {message.text}
            {message.setup && <p className="mt-1">{message.setup}</p>}
          </div>
        )}
      </Card>

      <OverviewPanel overview={dashboard.overview} projectId={projectId} />

      {metrics && metrics.branded_unknown > 0 && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-semibold">
            <span aria-hidden="true">⚠ </span>AI doesn&apos;t know your brand yet
          </p>
          <p className="mt-1">
            In {metrics.branded_unknown} of {metrics.branded_questions} answers to questions that name {dashboard.project.brand_name}, the AI said it
            couldn&apos;t find or doesn&apos;t know you ({metrics.branded_known} showed it knows you). These answers aren&apos;t counted as mentions.{" "}
            <Link href={`/projects/${projectId}/results?show=unknown`} className="font-medium underline underline-offset-2">
              See the answers
            </Link>
          </p>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card
          title="Action plan"
          actions={<Link href={`/projects/${projectId}/recommendations`} className="text-sm font-medium text-indigo-700 hover:underline">Open →</Link>}
        >
          {Object.values(dashboard.action_plan).every((n) => n === 0) ? (
            <p className="text-sm text-slate-500">Action items appear after an audit or visibility test completes.</p>
          ) : (
            <>
              <p className="mb-2 text-xs text-slate-500">Still to do, by impact</p>
              <dl className="grid grid-cols-3 gap-3 text-center">
                {(["high", "medium", "low"] as const).map((p) => (
                  <div key={p} className="rounded-lg border border-slate-200 p-3">
                    <dt className="text-xs capitalize text-slate-500">{p} impact</dt>
                    <dd className="mt-1 text-2xl font-semibold tabular-nums text-slate-900">{dashboard.recommendation_counts[p]}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-sm text-slate-600">
                {dashboard.action_plan.in_progress} in progress · {dashboard.action_plan.completed} completed ·{" "}
                {dashboard.action_plan.no_longer_detected} no longer detected
              </p>
            </>
          )}
          {dashboard.latest_audit_checks.length > 0 && (
            <div className="mt-5">
              <p className="text-sm font-medium text-slate-800">Failing audit checks</p>
              <ul className="mt-2 space-y-1 text-sm text-slate-600">
                {dashboard.latest_audit_checks.filter((c) => !c.passed).slice(0, 5).map((c) => (
                  <li key={c.id} className="flex gap-2"><span aria-hidden="true" className="text-rose-600">✕</span>{c.label}</li>
                ))}
                {dashboard.latest_audit_checks.every((c) => c.passed) && <li>All checks passed.</li>}
              </ul>
            </div>
          )}
        </Card>

        <Card title="Recent activity" actions={<Link href={`/projects/${projectId}/history`} className="text-sm font-medium text-indigo-700 hover:underline">Full history →</Link>}>
        {dashboard.recent_audits.length + dashboard.recent_runs.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing has run yet.</p>
        ) : (
          <ul className="divide-y divide-slate-100 text-sm">
            {[
              ...dashboard.recent_audits.map((a) => ({ kind: "Website audit", id: a.id, status: a.status, at: a.created_at, detail: a.score != null ? `Score ${a.score}/100` : a.error ?? a.progress_message ?? "", href: `/projects/${projectId}/audit?audit=${a.id}` })),
              ...dashboard.recent_runs.map((r) => ({ kind: "Visibility test", id: r.id, status: r.status, at: r.created_at, detail: `${r.model} · ${r.completed_questions}/${r.total_questions} processed${r.error ? ` · ${r.error}` : ""}`, href: `/projects/${projectId}/results?run=${r.id}` })),
            ]
              .sort((a, b) => b.at.localeCompare(a.at))
              .slice(0, 6)
              .map((item) => (
                <li key={item.kind + item.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={item.status} />
                    <Link href={item.href} className="font-medium text-slate-900 hover:underline">{item.kind} #{item.id}</Link>
                    <span className="text-slate-500">{item.detail}</span>
                  </div>
                  <span className="text-xs text-slate-400">{dateTime(item.at)}</span>
                </li>
              ))}
          </ul>
        )}
        </Card>
      </div>
    </div>
  );
}
