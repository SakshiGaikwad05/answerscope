"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { Badge, Card, EmptyState, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api, type AuditDetail, type AuditSummary } from "@/lib/api";
import { METRIC_DEFINITIONS, dateTime, isActive, shortUrl } from "@/lib/format";

const CATEGORY_TITLES: Record<string, string> = {
  crawlability: "Crawlability & access",
  metadata: "Metadata",
  structure: "Content structure",
  structured_data: "Structured data",
  content: "Content coverage",
};

function PassIcon({ passed, partial }: { passed: boolean; partial?: boolean }) {
  if (passed) return <span className="text-emerald-700" aria-label="Passed">✓</span>;
  return <span className={partial ? "text-amber-700" : "text-rose-700"} aria-label={partial ? "Partially passing" : "Failed"}>{partial ? "!" : "✕"}</span>;
}

function AuditView() {
  const { projectId, dashboard } = useProject();
  const search = useSearchParams();
  const router = useRouter();
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [detail, setDetail] = useState<AuditDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const latestJob = dashboard?.recent_audits[0];
  // Default to the most recent finished audit, failed ones included, so a fetch
  // failure is shown with its reason instead of "no completed audit".
  const latestFinished = dashboard?.recent_audits.find((a) => !isActive(a.status));
  const selectedId = Number(search.get("audit")) || latestFinished?.id || null;

  useEffect(() => {
    api.listAudits(projectId).then(setAudits).catch((e: Error) => setError(e.message));
  }, [projectId, latestJob?.status, latestJob?.id]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    api
      .getAudit(selectedId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [selectedId, latestJob?.status]);

  if (error) return <ErrorState message={error} />;

  const running = latestJob && isActive(latestJob.status);

  return (
    <div className="space-y-6">
      {running && (
        <div role="status" className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
          <StatusBadge status={latestJob.status} />
          Audit #{latestJob.id} in progress: {latestJob.progress_message ?? "working"}…
        </div>
      )}

      {audits && audits.length > 1 && (
        <div className="flex items-center gap-2 text-sm">
          <label htmlFor="audit-select" className="text-slate-600">Viewing</label>
          <select
            id="audit-select"
            value={selectedId ?? ""}
            onChange={(e) => router.replace(`/projects/${projectId}/audit?audit=${e.target.value}`)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5"
          >
            {audits.map((a) => (
              <option key={a.id} value={a.id}>
                Audit #{a.id} · {dateTime(a.created_at)} · {a.status}{a.score != null ? ` · ${a.score}/100` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      {!selectedId ? (
        running ? null : (
          <EmptyState title="No completed audit yet" description="Run the website audit from the Dashboard tab." />
        )
      ) : !detail || detail.id !== selectedId ? (
        <Loading label="Loading audit…" />
      ) : detail.status === "failed" ? (
        <div className="space-y-2">
          <ErrorState message={`Audit #${detail.id} failed: ${detail.error}`} />
          {detail.site_info.error && (
            <p className="text-xs text-slate-500">
              Reason code <span className="font-mono">{detail.site_info.error.code}</span>
              {detail.site_info.error.status_code != null && <> · HTTP {detail.site_info.error.status_code}</>}
              {detail.site_info.error.url && <> · {detail.site_info.error.url}</>}. No score was recorded for this audit.
            </p>
          )}
        </div>
      ) : detail.status !== "completed" ? (
        <Loading label={detail.progress_message ?? "Audit in progress…"} />
      ) : (
        <AuditDetailView audit={detail} />
      )}
    </div>
  );
}

function AuditDetailView({ audit }: { audit: AuditDetail }) {
  const grouped = audit.checks.reduce<Record<string, typeof audit.checks>>((acc, c) => {
    (acc[c.category] ||= []).push(c);
    return acc;
  }, {});
  const robots = audit.site_info.robots ?? {};
  const sitemap = audit.site_info.sitemap ?? {};
  const aiCrawlers = Object.entries(robots.ai_crawlers ?? {});

  return (
    <>
      <div className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <p className="text-sm font-medium text-slate-600">Audit score</p>
          <p className="mt-2 text-4xl font-semibold tabular-nums text-slate-900">{audit.score}<span className="text-xl text-slate-400">/100</span></p>
          <p className="mt-2 text-xs text-slate-500">{METRIC_DEFINITIONS.auditScore}</p>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm text-sm">
          <p className="font-medium text-slate-600">Crawl</p>
          <ul className="mt-2 space-y-1 text-slate-700">
            <li>{audit.pages_crawled} pages analyzed</li>
            <li>Started from <span className="font-mono text-xs">{shortUrl(audit.site_info.root_url ?? "")}</span></li>
            <li>robots.txt: {robots.found ? "found" : "not found"}</li>
            <li>Sitemap: {sitemap.found ? `${sitemap.url_count} URLs` : "not found"}</li>
            <li>Completed {dateTime(audit.completed_at)}</li>
          </ul>
        </div>
        <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm text-sm">
          <p className="font-medium text-slate-600">Checks</p>
          <p className="mt-2 text-slate-700">
            <span className="text-2xl font-semibold tabular-nums text-slate-900">{audit.checks.filter((c) => c.passed).length}</span> of {audit.checks.length} passed
          </p>
          {(audit.site_info.failures?.length ?? 0) > 0 && (
            <p className="mt-2 text-amber-800">{audit.site_info.failures!.length} page(s) could not be fetched</p>
          )}
          {audit.site_info.stopped_early && (
            <p className="mt-1 text-slate-600">Crawl stopped early: {audit.site_info.stopped_early}</p>
          )}
          {(audit.site_info.skipped_by_robots?.length ?? 0) > 0 && (
            <p className="mt-1 text-slate-600">{audit.site_info.skipped_by_robots!.length} page(s) skipped because robots.txt disallows them</p>
          )}
        </div>
      </div>

      {audit.site_info.js_rendered_shell && (
        <div role="status" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          <p className="font-semibold"><span aria-hidden="true">⚠ </span>This site&apos;s content only appears after JavaScript runs</p>
          <p className="mt-1">
            The homepage HTML is an empty app shell, so crawlers that don&apos;t run JavaScript (including most AI crawlers) see no text,
            headings or links. The content checks below describe what those crawlers see, not what visitors see in a browser. Fix this first,
            then re-run the audit.
          </p>
        </div>
      )}

      <Card title="Audit checks" description="Each check lists what was measured and the pages or values behind it.">
        <div className="space-y-6">
          {Object.entries(grouped).map(([cat, checks]) => (
            <div key={cat}>
              <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{CATEGORY_TITLES[cat] ?? cat}</h3>
              <ul className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                {checks.map((c) => (
                  <li key={c.id} className="p-3">
                    <details>
                      <summary className="flex cursor-pointer list-none items-start gap-3">
                        <span className="mt-0.5 w-4 text-center font-bold"><PassIcon passed={c.passed} partial={!c.passed && c.score > 0} /></span>
                        <span className="flex-1">
                          <span className="font-medium text-slate-900">{c.label}</span>
                          <span className="block text-sm text-slate-600">{c.detail}</span>
                        </span>
                        <span className="text-xs tabular-nums text-slate-500">{Math.round(c.score * 100)}% · weight {c.weight}</span>
                      </summary>
                      <div className="ml-7 mt-2 space-y-2 text-sm">
                        <p className="text-slate-600"><span className="font-medium text-slate-700">Why it matters: </span>{c.why}</p>
                        {c.evidence.length > 0 && (
                          <div>
                            <p className="font-medium text-slate-700">Evidence</p>
                            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-600">
                              {c.evidence.map((e) => <li key={e} className="break-all">{e}</li>)}
                            </ul>
                          </div>
                        )}
                      </div>
                    </details>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Questions your site answers" description="Common customer topics and whether any crawled page appears to cover them">
          <ul className="space-y-2 text-sm">
            {audit.content_gaps.map((g) => (
              <li key={g.topic} className="flex items-start gap-3">
                <span className="mt-0.5 w-4 text-center font-bold"><PassIcon passed={g.covered} /></span>
                <div>
                  <p className="font-medium text-slate-900">{g.label}</p>
                  <p className="text-slate-500">
                    {g.covered ? <>Covered by {g.pages.map(shortUrl).join(", ")}</> : <>Unanswered — e.g. “{g.example_question}”</>}
                  </p>
                </div>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-slate-500">Detected from page URLs, titles and headings of crawled pages only; uncrawled pages may cover these topics.</p>
        </Card>
        <Card title="AI crawler access" description="What robots.txt allows for the homepage">
          {aiCrawlers.length === 0 ? (
            <p className="text-sm text-slate-500">{robots.found ? "No rules evaluated." : "No robots.txt found, so all crawlers are allowed by default."}</p>
          ) : (
            <table className="w-full text-sm">
              <caption className="sr-only">AI crawler access according to robots.txt</caption>
              <thead><tr className="text-left text-slate-500"><th className="py-1 font-medium">Crawler</th><th className="py-1 font-medium">Purpose</th><th className="py-1 font-medium">Access</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {aiCrawlers.map(([agent, info]) => (
                  <tr key={agent}>
                    <td className="py-1.5 font-mono text-xs">{agent}</td>
                    <td className="py-1.5 text-slate-600">{info.description}</td>
                    <td className="py-1.5">{info.allowed ? <Badge tone="good">✓ allowed</Badge> : <Badge tone="bad">✕ blocked</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <Card title={`Crawled pages (${audit.pages.length})`} description="Expand a page to see its extracted metadata, headings and issues">
        <ul className="divide-y divide-slate-100">
          {audit.pages.map((p) => (
            <li key={p.id} className="py-3">
              <details>
                <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-900">{shortUrl(p.url)}</span>
                  {p.has_faq && <Badge tone="accent">FAQ</Badge>}
                  {p.schema_types.length > 0 && <Badge>{p.schema_types.length} schema types</Badge>}
                  <Badge tone={p.issues.some((i) => i.severity === "high") ? "bad" : p.issues.length ? "warning" : "good"}>
                    {p.issues.length} issue{p.issues.length === 1 ? "" : "s"}
                  </Badge>
                  <span className="text-xs tabular-nums text-slate-500">{p.word_count} words</span>
                </summary>
                <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
                  <dt className="text-slate-500">URL</dt><dd className="break-all"><a href={p.url} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:underline">{p.url}</a></dd>
                  <dt className="text-slate-500">Title</dt><dd>{p.title ?? <em className="text-rose-700">missing</em>}</dd>
                  <dt className="text-slate-500">Meta description</dt><dd>{p.meta_description ?? <em className="text-rose-700">missing</em>}</dd>
                  <dt className="text-slate-500">H1</dt><dd>{p.h1.length ? p.h1.join(" | ") : <em className="text-rose-700">missing</em>}</dd>
                  <dt className="text-slate-500">Structured data</dt><dd>{p.schema_types.join(", ") || "none"}</dd>
                  <dt className="text-slate-500">Links</dt><dd>{p.internal_links} internal · {p.external_links} external</dd>
                  {p.faq_questions.length > 0 && (<><dt className="text-slate-500">FAQ questions</dt><dd>{p.faq_questions.slice(0, 5).join(" · ")}</dd></>)}
                  {p.headings.length > 0 && (
                    <>
                      <dt className="text-slate-500">Headings</dt>
                      <dd><ul className="space-y-0.5">{p.headings.slice(0, 12).map((h, i) => <li key={i} style={{ paddingLeft: `${(h.level - 1) * 12}px` }} className="text-slate-700"><span className="font-mono text-xs text-slate-400">H{h.level}</span> {h.text}</li>)}</ul></dd>
                    </>
                  )}
                  {p.text_excerpt && (
                    <>
                      <dt className="text-slate-500">Extracted text</dt>
                      <dd className="max-h-40 overflow-y-auto text-slate-600">{p.text_excerpt}{p.text_excerpt.length >= 2000 && "…"}</dd>
                    </>
                  )}
                  {p.issues.length > 0 && (
                    <>
                      <dt className="text-slate-500">Issues</dt>
                      <dd><ul className="space-y-1">{p.issues.map((i) => <li key={i.code + i.message} className="flex gap-2"><Badge tone={i.severity === "high" ? "bad" : i.severity === "medium" ? "warning" : "neutral"}>{i.severity}</Badge>{i.message}</li>)}</ul></dd>
                    </>
                  )}
                </dl>
              </details>
            </li>
          ))}
        </ul>
      </Card>
    </>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<Loading />}>
      <AuditView />
    </Suspense>
  );
}
