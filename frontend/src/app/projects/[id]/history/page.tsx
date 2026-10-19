"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { Card, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api, type AuditSummary, type RunSummary } from "@/lib/api";
import { dateTime } from "@/lib/format";

export default function HistoryPage() {
  const { projectId, dashboard } = useProject();
  const [audits, setAudits] = useState<AuditSummary[] | null>(null);
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const auditStatus = dashboard?.recent_audits[0]?.status;
  const runStatus = dashboard?.recent_runs[0]?.status;

  useEffect(() => {
    Promise.all([api.listAudits(projectId), api.listRuns(projectId)])
      .then(([a, r]) => { setAudits(a); setRuns(r); })
      .catch((e: Error) => setError(e.message));
  }, [projectId, auditStatus, runStatus]);

  if (error) return <ErrorState message={error} />;
  if (!audits || !runs) return <Loading />;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title={`Website audits (${audits.length})`} description="Every audit is stored; open one to see its full results.">
        {audits.length === 0 ? <p className="text-sm text-slate-500">No audits yet.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {audits.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <div className="flex items-center gap-2">
                  <StatusBadge status={a.status} />
                  <Link href={`/projects/${projectId}/audit?audit=${a.id}`} className="font-medium text-slate-900 hover:underline">Audit #{a.id}</Link>
                  <span className="text-slate-500">{a.score != null ? `${a.score}/100 · ${a.pages_crawled} pages` : a.error ?? a.progress_message}</span>
                </div>
                <span className="text-xs text-slate-400">{dateTime(a.created_at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={`Visibility tests (${runs.length})`} description="Runs with different models or settings aren't directly comparable.">
        {runs.length === 0 ? <p className="text-sm text-slate-500">No visibility tests yet.</p> : (
          <ul className="divide-y divide-slate-100 text-sm">
            {runs.map((r) => (
              <li key={r.id} className="py-2.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <StatusBadge status={r.status} />
                    <Link href={`/projects/${projectId}/results?run=${r.id}`} className="font-medium text-slate-900 hover:underline">Run #{r.id}</Link>
                    <span className="text-slate-500">{r.completed_questions}/{r.total_questions} answered</span>
                  </div>
                  <span className="text-xs text-slate-400">{dateTime(r.created_at)}</span>
                </div>
                <p className="mt-1 text-xs text-slate-500">
                  {r.provider} · <span className="font-mono">{r.model}</span> · web search {r.conditions.web_search ? "on" : "off"} · {r.conditions.competitors?.length ?? 0} competitors tracked
                  {r.error && <span className="text-rose-700"> · {r.error}</span>}
                </p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
