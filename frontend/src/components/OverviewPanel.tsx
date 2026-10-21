"use client";

import Link from "next/link";

import { Badge, Card, StatusBadge, cx } from "@/components/ui";
import { REC_GROUPS, type Overview } from "@/lib/api";
import { dateTime, pct } from "@/lib/format";

function ScoreCard({ label, value, suffix, missing, children }: {
  label: string; value: number | null | undefined; suffix?: string; missing: string; children?: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-medium text-slate-600">{label}</p>
        <Badge tone="neutral">observed</Badge>
      </div>
      {value == null ? (
        <p className="mt-2 text-sm text-slate-500">
          <span className="block text-2xl font-semibold text-slate-300">Not measured</span>
          {missing}
        </p>
      ) : (
        <p className="mt-2 text-3xl font-semibold tabular-nums text-slate-900">
          {value}
          {suffix && <span className="text-lg text-slate-400">{suffix}</span>}
        </p>
      )}
      {children && <div className="mt-2 text-xs leading-relaxed text-slate-500">{children}</div>}
    </div>
  );
}

const groupLabel = (g: string) => REC_GROUPS.find((x) => x.id === g)?.label ?? g;

export function OverviewPanel({ overview: o, projectId }: { overview: Overview; projectId: number }) {
  const anyTested = o.assistants.some((a) => a.metrics);
  return (
    <section aria-labelledby="overview-heading" className="space-y-4">
      <h2 id="overview-heading" className="text-lg font-semibold text-slate-900">Overview</h2>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <ScoreCard label="AI visibility score" value={o.ai_visibility.score} suffix="%" missing="Run an AI visibility test to measure it.">
          <details>
            <summary className="cursor-pointer text-indigo-700">How it&apos;s calculated</summary>
            <p className="mt-1">{o.ai_visibility.formula}</p>
            {o.ai_visibility.included.length > 0 && (
              <p className="mt-1">Included: {o.ai_visibility.included.map((i) => `${i.assistant} ${pct(i.unprompted_mention_rate)}`).join(" · ")}</p>
            )}
            {o.ai_visibility.excluded.length > 0 && <p className="mt-1">Excluded: {o.ai_visibility.excluded.join(" · ")}</p>}
          </details>
        </ScoreCard>
        <ScoreCard label="Website health" value={o.website_health.score} suffix="/100" missing="Run the website audit.">
          Weighted score of the technical and content audit checks.
        </ScoreCard>
        <ScoreCard label="Local SEO completeness" value={o.local_seo.score} suffix="%" missing={o.local_seo.note ?? "No local checks could be measured yet."}>
          {o.local_seo.score != null && (
            <>Share of local checks passed ({o.local_seo.measured} measured{o.local_seo.unknown ? `, ${o.local_seo.unknown} need more info and aren't counted` : ""}).</>
          )}
        </ScoreCard>
        <ScoreCard
          label="Backlinks & mentions"
          value={o.backlinks.discovered ? o.backlinks.existing ?? 0 : null}
          missing="Run backlink discovery on the Backlinks tab."
        >
          {o.backlinks.discovered && (
            <>Existing links/mentions found. {o.backlinks.verified ?? 0} verified after completion · {o.backlinks.suggested ?? 0} opportunities to act on. Search results are not a complete backlink index.</>
          )}
        </ScoreCard>
      </div>

      <Card title="Assistant by assistant" description="Latest completed test for each assistant. Results come from each provider's API, not its consumer app.">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] text-sm">
            <caption className="sr-only">AI visibility per assistant</caption>
            <thead>
              <tr className="border-b border-slate-200 text-left text-slate-500">
                <th className="py-2 font-medium">Assistant</th>
                <th className="py-2 text-right font-medium">Unprompted mentions</th>
                <th className="py-2 text-right font-medium">All mentions</th>
                <th className="py-2 text-right font-medium">Website cited</th>
                <th className="py-2 text-right font-medium">Avg. list position</th>
                <th className="py-2 text-right font-medium">Mentions your area</th>
                <th className="py-2 pl-4 font-medium">Last test</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 tabular-nums">
              {o.assistants.map((a) => (
                <tr key={a.provider} className="align-top">
                  <td className="py-2 font-medium text-slate-900" title={a.experience}>{a.assistant}</td>
                  {a.metrics ? (
                    <>
                      <td className="py-2 text-right">{pct(a.metrics.unbranded_mention_rate)}</td>
                      <td className="py-2 text-right">{pct(a.metrics.brand_mention_rate)}</td>
                      <td className="py-2 text-right">{pct(a.metrics.website_citation_rate)}</td>
                      <td className="py-2 text-right">
                        {a.metrics.average_position != null ? `#${a.metrics.average_position}` : <span className="text-slate-400" title={`${a.metrics.answers_with_list} answers had a list`}>not listed</span>}
                      </td>
                      <td className="py-2 text-right">{a.metrics.location_relevance_rate != null ? pct(a.metrics.location_relevance_rate) : <span className="text-slate-400">no city set</span>}</td>
                      <td className="py-2 pl-4 text-xs text-slate-500">
                        <Link href={`/projects/${projectId}/results?run=${a.run_id}`} className="text-indigo-700 hover:underline">{dateTime(a.tested_at)}</Link>
                        {a.metrics.questions_failed > 0 && <span className="block text-amber-700">{a.metrics.questions_failed} questions failed</span>}
                      </td>
                    </>
                  ) : (
                    <td colSpan={6} className={cx("py-2 text-sm", a.configured ? "text-slate-500" : "text-slate-400")}>
                      {a.latest_status && a.latest_status !== "completed" ? (
                        <span className="inline-flex items-center gap-2"><StatusBadge status={a.latest_status} />{a.latest_error}</span>
                      ) : a.configured ? (
                        "Not tested yet."
                      ) : (
                        <>Not connected · <Link href="/keys" className="font-medium text-indigo-700 hover:underline">Add your {a.assistant} key</Link></>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!anyTested && <p className="mt-3 text-sm text-slate-500">No assistant has been tested yet; missing results are shown as not measured, never as zero.</p>}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Who AI recommends instead" description="Competitors and other businesses appearing in the latest answers">
          {o.competitors.length === 0 && o.other_businesses.length === 0 ? (
            <p className="text-sm text-slate-500">No competitors recorded yet. Add competitors in Settings, then run a test.</p>
          ) : (
            <ul className="space-y-1.5 text-sm">
              {o.competitors.map((c) => (
                <li key={c.name} className="flex justify-between gap-2">
                  <span>{c.name} <span className="text-xs text-slate-500">(tracked)</span></span>
                  <span className="tabular-nums text-slate-700">{pct(c.average_mention_rate)} avg across {c.assistants} assistant{c.assistants === 1 ? "" : "s"}</span>
                </li>
              ))}
              {o.other_businesses.map((b) => (
                <li key={b.name} className="flex justify-between gap-2">
                  <span>{b.name} <Badge tone="warning">AI-extracted</Badge></span>
                  <span className="tabular-nums text-slate-700">{b.answers} answer{b.answers === 1 ? "" : "s"}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Top actions" actions={<Link href={`/projects/${projectId}/recommendations`} className="text-sm font-medium text-indigo-700 hover:underline">Action plan →</Link>}>
          {o.top_actions.length === 0 ? (
            <p className="text-sm text-slate-500">No open actions. Run the audit and a visibility test to find opportunities.</p>
          ) : (
            <ol className="space-y-2 text-sm">
              {o.top_actions.map((t) => (
                <li key={t.id} className="flex flex-wrap items-start gap-2">
                  {t.blocking && <Badge tone="bad">Do first</Badge>}
                  <span className="flex-1 text-slate-800">{t.issue}</span>
                  <span className="text-xs text-slate-500">{groupLabel(t.group)} · {t.priority} impact · {t.effort} effort</span>
                </li>
              ))}
            </ol>
          )}
        </Card>
      </div>
    </section>
  );
}
