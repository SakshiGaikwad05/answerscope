"use client";

import { useEffect, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, cx } from "@/components/ui";
import { api, type BacklinkItem } from "@/lib/api";
import { dateTime } from "@/lib/format";

const CATEGORY_LABELS: Record<string, string> = {
  directory: "Directory", chamber_association: "Chamber / association", news: "Local news", review_platform: "Review platform",
  community_events: "Community / events", supplier_partner: "Supplier / partner", blog_resource: "Blog / resource page", other: "Other",
};
const VALUE_LABELS: Record<string, string> = { backlink: "Link", mention: "Mention", both: "Link + mention", unknown: "Not yet" };

function RelBadge({ item }: { item: BacklinkItem }) {
  if (item.link_rel === "unknown") return <Badge tone="neutral">follow/nofollow: not verifiable yet</Badge>;
  return <Badge tone={item.link_rel === "follow" ? "good" : "neutral"}>{item.link_rel}</Badge>;
}

function Item({ item, onChange, onRemove }: { item: BacklinkItem; onChange: (i: BacklinkItem) => void; onRemove: (id: number) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function run(key: string, fn: () => Promise<BacklinkItem | void>) {
    setBusy(key);
    setError(null);
    try {
      const r = await fn();
      if (r) onChange(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <li className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="font-medium text-indigo-700 hover:underline break-all">
            {item.title || item.domain}
          </a>
          <p className="text-xs text-slate-500 break-all">{item.url}</p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Badge>{CATEGORY_LABELS[item.category] ?? item.category}</Badge>
          <Badge tone={item.value_type === "unknown" ? "neutral" : "good"}>{VALUE_LABELS[item.value_type]}</Badge>
          <RelBadge item={item} />
        </div>
      </div>
      <dl className="mt-2 space-y-1 text-sm">
        {item.relevance && <div><dt className="inline font-medium text-slate-700">Relevance: </dt><dd className="inline text-slate-600">{item.relevance}</dd></div>}
        {item.why_it_helps && <div><dt className="inline font-medium text-slate-700">Why it could help: </dt><dd className="inline text-slate-600">{item.why_it_helps}</dd></div>}
        {item.submission_url && (
          <div><dt className="inline font-medium text-slate-700">Submission page: </dt>
            <dd className="inline"><a href={item.submission_url} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:underline break-all">{item.submission_url}</a></dd></div>
        )}
      </dl>
      {item.evidence.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-slate-600">Evidence ({item.evidence.length})</summary>
          <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-600">{item.evidence.map((e, i) => <li key={i} className="break-words">{e}</li>)}</ul>
        </details>
      )}
      {item.outreach && (
        <div className="mt-2 rounded-md bg-slate-50 p-2 text-sm text-slate-700">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Suggested next step / outreach (review before sending)</span>
            <button type="button" className="text-xs font-medium text-indigo-700 hover:underline"
              onClick={async () => { try { await navigator.clipboard.writeText(item.outreach!); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* clipboard unavailable */ } }}>
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <p className="mt-1 whitespace-pre-wrap">{item.outreach}</p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3 text-sm">
        {item.kind === "opportunity" && item.status !== "verified" && (
          <label className="flex items-center gap-2">
            <span className="text-slate-600">Status</span>
            <select
              value={["suggested", "in_progress", "completed", "dismissed"].includes(item.status) ? item.status : "completed"}
              disabled={!!busy}
              onChange={(e) => run("status", () => api.updateBacklink(item.id, { status: e.target.value as "suggested" }))}
              className="rounded-lg border border-slate-300 bg-white px-2 py-1"
              aria-label={`Status for ${item.domain}`}
            >
              <option value="suggested">To do</option>
              <option value="in_progress">In progress</option>
              <option value="completed">Completed</option>
              <option value="dismissed">Not relevant</option>
            </select>
          </label>
        )}
        <Button variant="secondary" loading={busy === "verify"} onClick={() => run("verify", () => api.verifyBacklink(item.id))}>
          {item.kind === "existing" ? "Re-check" : "Verify now"}
        </Button>
        <Button variant="ghost" onClick={() => run("delete", async () => { await api.deleteBacklink(item.id); onRemove(item.id); })}>Remove</Button>
        <span className="ml-auto text-xs text-slate-500">
          {item.last_checked_at ? `Checked ${dateTime(item.last_checked_at)}` : "Not checked"}
          {item.verified_at && ` · verified ${dateTime(item.verified_at)}`}
        </span>
      </div>
      {item.status === "not_found" && (
        <p role="status" className="mt-2 rounded-md bg-amber-50 px-2 py-1 text-sm text-amber-900">
          {item.kind === "existing" ? "The link or mention is no longer on this page." : "Marked completed, but the page doesn't show your business yet. Listings can take days to go live."}
        </p>
      )}
      {item.check_error && <p className="mt-2 text-sm text-amber-800">Last check failed: {item.check_error}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
    </li>
  );
}

const SECTIONS: { id: string; title: string; description: string; test: (i: BacklinkItem) => boolean }[] = [
  { id: "existing", title: "1. Existing links and mentions", description: "Pages found in search results that already link to or mention you (verified by reading the page).",
    test: (i) => i.kind === "existing" },
  { id: "opportunities", title: "2. Opportunities", description: "Legitimate, relevant places to get listed or mentioned. Each page was loaded and checked.",
    test: (i) => i.kind === "opportunity" && ["suggested", "in_progress"].includes(i.status) },
  { id: "completed", title: "3. Completed by you", description: "Marked completed. Use 'Verify now' to check that the link or mention is live.",
    test: (i) => i.kind === "opportunity" && ["completed", "not_found"].includes(i.status) },
  { id: "verified", title: "4. Verified after completion", description: "Your business now appears on these pages (confirmed by fetching them).",
    test: (i) => i.kind === "opportunity" && i.status === "verified" },
];

export default function BacklinksPage() {
  const { projectId, refresh, dashboard } = useProject();
  const [data, setData] = useState<Awaited<ReturnType<typeof api.backlinks>> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState(false);
  const [notice, setNotice] = useState<{ ok: boolean; text: string } | null>(null);
  const [url, setUrl] = useState("");
  const [adding, setAdding] = useState(false);
  const [showDismissed, setShowDismissed] = useState(false);

  useEffect(() => {
    api.backlinks(projectId).then(setData).catch((e: Error) => setError(e.message));
  }, [projectId]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <Loading label="Loading backlinks…" />;
  const items = data.items;
  const update = (i: BacklinkItem) => setData((d) => d && { ...d, items: d.items.map((x) => (x.id === i.id ? i : x)) });
  const remove = (id: number) => setData((d) => d && { ...d, items: d.items.filter((x) => x.id !== id) });
  const quota = dashboard?.usage?.backlink_discovery;

  async function discover() {
    setDiscovering(true);
    setNotice(null);
    try {
      const found = await api.discoverBacklinks(projectId);
      setData((d) => d && { ...d, items: found });
      setNotice({ ok: true, text: `Search complete: ${found.length} verified page(s) tracked. Pages that didn't load or looked like link selling were excluded.` });
      await refresh();
    } catch (e) {
      setNotice({ ok: false, text: (e as Error).message });
    } finally {
      setDiscovering(false);
    }
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    setAdding(true);
    setNotice(null);
    try {
      const item = await api.addBacklink(projectId, url.trim());
      setData((d) => d && { ...d, items: [...d.items, item] });
      setUrl("");
    } catch (err) {
      setNotice({ ok: false, text: (err as Error).message });
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card title="Backlinks & brand mentions" description="Find legitimate places that can link to or mention your business, and track them until they're live.">
        {!data.search_configured ? (
          <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{data.setup}</p>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={discover} loading={discovering} disabled={quota?.remaining === 0}>
              {discovering ? "Searching and checking pages… (up to 2 minutes)" : "Find opportunities and mentions"}
            </Button>
            <span className="text-xs text-slate-500">
              Uses the {data.search_backend} search API{quota && ` · ${quota.remaining} of ${quota.limit} searches left today`}. Results are cached for 7 days.
            </span>
          </div>
        )}
        <form onSubmit={add} className="mt-4 flex flex-wrap items-end gap-2">
          <div className="min-w-[16rem] flex-1">
            <label htmlFor="bl-url" className="text-sm font-medium text-slate-800">Track a page you found yourself</label>
            <input id="bl-url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://example-directory.com/your-city"
                   className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
          <Button type="submit" variant="secondary" loading={adding} disabled={!url.trim()}>Add & check</Button>
        </form>
        {notice && <p role={notice.ok ? "status" : "alert"} className={cx("mt-3 rounded-lg px-3 py-2 text-sm", notice.ok ? "bg-emerald-50 text-emerald-900" : "bg-rose-50 text-rose-800")}>{notice.text}</p>}
        <p className="mt-3 text-xs text-slate-500">
          No authority scores are shown: they can&apos;t be measured honestly from search results. Search results are not a complete index of
          every link to your site. Never buy links or mass-submit; earned, accurate listings are what help. Backlinks don&apos;t guarantee AI recommendations.
        </p>
      </Card>

      {items.length === 0 ? (
        <EmptyState title="Nothing tracked yet" description={data.search_configured ? "Run a search to find opportunities and existing mentions." : "Add a page manually, or configure a search API."} />
      ) : (
        SECTIONS.map((sec) => {
          const list = items.filter(sec.test);
          return (
            <section key={sec.id} aria-labelledby={`sec-${sec.id}`}>
              <h2 id={`sec-${sec.id}`} className="text-base font-semibold text-slate-900">{sec.title} <span className="font-normal text-slate-500">({list.length})</span></h2>
              <p className="text-sm text-slate-500">{sec.description}</p>
              {list.length === 0 ? <p className="mt-2 text-sm text-slate-400">None.</p> : (
                <ul className="mt-3 space-y-3">{list.map((i) => <Item key={i.id} item={i} onChange={update} onRemove={remove} />)}</ul>
              )}
            </section>
          );
        })
      )}
      {items.some((i) => i.status === "dismissed") && (
        <div>
          <button className="text-sm text-indigo-700 hover:underline" onClick={() => setShowDismissed((v) => !v)}>
            {showDismissed ? "Hide" : "Show"} items marked not relevant ({items.filter((i) => i.status === "dismissed").length})
          </button>
          {showDismissed && <ul className="mt-3 space-y-3">{items.filter((i) => i.status === "dismissed").map((i) => <Item key={i.id} item={i} onChange={update} onRemove={remove} />)}</ul>}
        </div>
      )}
    </div>
  );
}
