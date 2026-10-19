"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Suspense, type ReactNode } from "react";

import { ProjectProvider, useProject } from "@/components/ProjectContext";
import { ErrorState, Loading, cx } from "@/components/ui";

const TABS = [
  { href: "", label: "Dashboard" },
  { href: "/audit", label: "Website audit" },
  { href: "/results", label: "Questions & results" },
  { href: "/competitors", label: "Competitors" },
  { href: "/recommendations", label: "Action plan" },
  { href: "/compare", label: "Compare" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

function Shell({ children }: { children: ReactNode }) {
  const { dashboard, error, refresh, projectId } = useProject();
  const pathname = usePathname();
  const base = `/projects/${projectId}`;

  if (error && !dashboard) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <ErrorState message={error} onRetry={() => void refresh()} />
      </div>
    );
  }
  if (!dashboard) return <Loading label="Loading project…" />;
  const p = dashboard.project;

  return (
    <div className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-slate-500">
            <Link href="/projects" className="hover:underline">Projects</Link> / {p.domain}
          </p>
          <h1 className="mt-1 text-2xl font-semibold text-slate-900">{p.brand_name}</h1>
          <p className="text-sm text-slate-500">
            <a href={p.website_url} target="_blank" rel="noopener noreferrer" className="hover:underline">{p.website_url}</a>
            {p.industry && <> · {p.industry}</>}
            {p.competitors.length > 0 && <> · vs {p.competitors.map((c) => c.name).join(", ")}</>}
          </p>
        </div>
      </div>
      <nav aria-label="Project sections" className="mt-6 overflow-x-auto border-b border-slate-200">
        <ul className="flex min-w-max gap-1">
          {TABS.map((t) => {
            const href = base + t.href;
            const active = t.href === "" ? pathname === base : pathname.startsWith(href);
            return (
              <li key={t.label}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={cx(
                    "inline-block border-b-2 px-3 py-2.5 text-sm font-medium",
                    active ? "border-accent text-indigo-700" : "border-transparent text-slate-600 hover:text-slate-900",
                  )}
                >
                  {t.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
      <div className="mt-6">{children}</div>
    </div>
  );
}

function ProjectFromParams({ children }: { children: ReactNode }) {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  if (!Number.isInteger(id) || id <= 0) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10">
        <ErrorState message="Invalid project id." />
      </div>
    );
  }
  return (
    <ProjectProvider projectId={id}>
      <Shell>{children}</Shell>
    </ProjectProvider>
  );
}

export default function ProjectLayout({ children }: { children: ReactNode }) {
  // useParams() is runtime data, so it must render inside a Suspense boundary.
  return (
    <Suspense fallback={<Loading label="Loading project…" />}>
      <ProjectFromParams>{children}</ProjectFromParams>
    </Suspense>
  );
}
