"use client";

import { useRouter } from "next/navigation";
import { useState, useSyncExternalStore } from "react";

import { CompetitorFields, cleanCompetitors, type CompetitorDraft } from "@/components/CompetitorFields";
import { Button, Card } from "@/components/ui";
import { api } from "@/lib/api";

const noopSubscribe = () => () => {};

export default function NewProjectPage() {
  const router = useRouter();
  // False during server rendering and until React has hydrated the form. Until
  // then a submit would be a plain HTML form post that never reaches the API.
  const interactive = useSyncExternalStore(noopSubscribe, () => true, () => false);
  const [websiteUrl, setWebsiteUrl] = useState("");
  const [brand, setBrand] = useState("");
  const [industry, setIndustry] = useState("");
  const [competitors, setCompetitors] = useState<CompetitorDraft[]>([{ name: "", website_url: "" }]);
  const [startAudit, setStartAudit] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!websiteUrl.trim() || !brand.trim()) {
      setError("Website URL and brand name are required.");
      return;
    }
    setSubmitting(true);
    try {
      const project = await api.createProject({
        website_url: websiteUrl.trim(),
        brand_name: brand.trim(),
        industry: industry.trim() || undefined,
        competitors: cleanCompetitors(competitors),
      });
      if (startAudit) await api.startAudit(project.id);
      router.push(`/projects/${project.id}`);
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <h1 className="text-2xl font-semibold text-slate-900">New project</h1>
      <p className="mt-1 text-sm text-slate-500">Tell us which brand and website to analyze.</p>

      <Card className="mt-6">
        <form onSubmit={onSubmit} method="post" className="space-y-5" noValidate>
          <div>
            <label htmlFor="website" className="text-sm font-medium text-slate-800">Website URL</label>
            <input
              id="website"
              required
              value={websiteUrl}
              onChange={(e) => setWebsiteUrl(e.target.value)}
              placeholder="https://www.example.com"
              inputMode="url"
              autoComplete="url"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              aria-describedby="website-help"
            />
            <p id="website-help" className="mt-1 text-xs text-slate-500">
              Public websites only. Local and private network addresses are blocked.
            </p>
          </div>
          <div>
            <label htmlFor="brand" className="text-sm font-medium text-slate-800">Brand / company name</label>
            <input
              id="brand"
              required
              maxLength={200}
              value={brand}
              onChange={(e) => setBrand(e.target.value)}
              placeholder="Example Inc."
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label htmlFor="industry" className="text-sm font-medium text-slate-800">
              Industry or category <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <input
              id="industry"
              maxLength={200}
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. project management software"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
            />
            <p className="mt-1 text-xs text-slate-500">Used to phrase category questions like “What are the best … ?”</p>
          </div>
          <CompetitorFields value={competitors} onChange={setCompetitors} />
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={startAudit} onChange={(e) => setStartAudit(e.target.checked)} className="h-4 w-4" />
            Start the website audit right away
          </label>
          {error && (
            <p role="alert" className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-800">{error}</p>
          )}
          <div className="flex justify-end">
            <Button type="submit" loading={submitting} disabled={!interactive}>
              {interactive ? "Create project" : "Loading…"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
