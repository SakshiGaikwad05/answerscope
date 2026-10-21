"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { CompetitorFields, cleanCompetitors, type CompetitorDraft } from "@/components/CompetitorFields";
import { EMPTY_LOCAL, LocalProfileFields, localDraftFrom, localPayload, type LocalDraft } from "@/components/LocalProfileFields";
import { useProject } from "@/components/ProjectContext";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";

export default function SettingsPage() {
  const { dashboard, refresh, projectId } = useProject();
  const router = useRouter();
  const project = dashboard?.project;
  const [industry, setIndustry] = useState(project?.industry ?? "");
  const [local, setLocal] = useState<LocalDraft>(project ? localDraftFrom(project) : EMPTY_LOCAL);
  const [competitors, setCompetitors] = useState<CompetitorDraft[]>(
    project?.competitors.map((c) => ({ name: c.name, website_url: c.website_url ?? "" })) ?? [],
  );
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);

  if (!project) return null;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMessage(null);
    try {
      await api.updateProject(projectId, { industry: industry.trim() || null, competitors: cleanCompetitors(competitors), ...localPayload(local) });
      await refresh();
      setMessage({ ok: true, text: "Saved. New settings apply to the next questions and visibility test; past runs keep their original conditions." });
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!window.confirm(`Delete ${project!.brand_name} and all of its audits, questions and results? This cannot be undone.`)) return;
    try {
      await api.deleteProject(projectId);
      router.push("/projects");
    } catch (err) {
      setMessage({ ok: false, text: (err as Error).message });
    }
  }

  return (
    <div className="max-w-2xl space-y-6">
      <Card title="Project settings" description={`Website and brand name are fixed: ${project.website_url} · ${project.brand_name}`}>
        <form onSubmit={save} className="space-y-5">
          <div>
            <label htmlFor="industry" className="text-sm font-medium text-slate-800">Industry or category</label>
            <input id="industry" value={industry} maxLength={200} onChange={(e) => setIndustry(e.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <LocalProfileFields value={local} onChange={setLocal} />
          <CompetitorFields value={competitors} onChange={setCompetitors} />
          {message && <p role={message.ok ? "status" : "alert"} className={`rounded-lg px-3 py-2 text-sm ${message.ok ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-800"}`}>{message.text}</p>}
          <div className="flex justify-end"><Button type="submit" loading={saving}>Save changes</Button></div>
        </form>
      </Card>
      <Card title="Danger zone">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-slate-600">Permanently delete this project and its history.</p>
          <Button variant="danger" onClick={remove}>Delete project</Button>
        </div>
      </Card>
    </div>
  );
}
