"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api, type Dashboard } from "@/lib/api";
import { isActive } from "@/lib/format";

interface ProjectContextValue {
  projectId: number;
  dashboard: Dashboard | null;
  error: string | null;
  refresh: () => Promise<void>;
  /** True while an audit or visibility run for this project is pending/running. */
  jobActive: boolean;
}

const Ctx = createContext<ProjectContextValue | null>(null);

export function ProjectProvider({ projectId, children }: { projectId: number; children: ReactNode }) {
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const d = await api.dashboard(projectId);
      setDashboard(d);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  const jobActive = Boolean(
    dashboard && (isActive(dashboard.recent_audits[0]?.status) || isActive(dashboard.recent_runs[0]?.status)),
  );

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial data load
    void refresh();
  }, [refresh]);

  // Poll while a background job runs so progress and results appear live.
  useEffect(() => {
    if (!jobActive) return;
    timer.current = setTimeout(() => void refresh(), 2500);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [jobActive, dashboard, refresh]);

  return <Ctx.Provider value={{ projectId, dashboard, error, refresh, jobActive }}>{children}</Ctx.Provider>;
}

export function useProject(): ProjectContextValue {
  const v = useContext(Ctx);
  if (!v) throw new Error("useProject must be used inside ProjectProvider");
  return v;
}
