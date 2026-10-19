"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ButtonLink, EmptyState, ErrorState, Loading } from "@/components/ui";
import { api, type ProjectListItem } from "@/lib/api";
import { dateTime, pct } from "@/lib/format";

export default function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .listProjects()
      .then((p) => {
        setProjects(p);
        setError(null);
      })
      .catch((e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Projects</h1>
          <p className="mt-1 text-sm text-slate-500">Each project tracks one brand and its website.</p>
        </div>
        <ButtonLink href="/projects/new">New project</ButtonLink>
      </div>

      <div className="mt-8">
        {error ? (
          <ErrorState message={error} onRetry={load} />
        ) : projects === null ? (
          <Loading label="Loading projects…" />
        ) : projects.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Create a project with your website URL and brand name to run your first audit."
            action={<ButtonLink href="/projects/new">Create your first project</ButtonLink>}
          />
        ) : (
          <ul className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <li key={p.id}>
                <Link
                  href={`/projects/${p.id}`}
                  className="block h-full rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-indigo-300 hover:shadow"
                >
                  <p className="font-semibold text-slate-900">{p.brand_name}</p>
                  <p className="text-sm text-slate-500">{p.domain}</p>
                  {p.industry && <p className="mt-1 text-xs text-slate-500">{p.industry}</p>}
                  <dl className="mt-4 grid grid-cols-2 gap-2 text-sm">
                    <div>
                      <dt className="text-slate-500">Audit score</dt>
                      <dd className="font-semibold tabular-nums text-slate-900">
                        {p.latest_audit_score === null ? "Not audited" : `${p.latest_audit_score}/100`}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Unprompted mentions</dt>
                      <dd className="font-semibold tabular-nums text-slate-900">
                        {p.latest_unprompted_mention_rate === null
                          ? p.latest_brand_mention_rate === null ? "Not tested" : "—"
                          : pct(p.latest_unprompted_mention_rate)}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-4 text-xs text-slate-400">Last activity {dateTime(p.latest_activity)}</p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
