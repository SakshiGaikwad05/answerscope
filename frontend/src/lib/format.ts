export const CATEGORY_LABELS: Record<string, string> = {
  best_in_category: "Best in category",
  recommendation: "Brand recommendation",
  alternatives: "Alternatives",
  comparison: "Comparison",
  pricing: "Pricing",
  features: "Features",
  use_case: "Use case",
  beginner: "Beginner-friendly",
};

export function pct(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return (u.hostname.replace(/^www\./, "") + u.pathname).replace(/\/$/, "");
  } catch {
    return url;
  }
}

export function isActive(status: string | undefined): boolean {
  return status === "pending" || status === "running";
}

/** Metric definitions shown next to every number on the dashboard. */
export const METRIC_DEFINITIONS = {
  questionsTested:
    "Questions the AI provider answered successfully in the latest completed visibility run. Failed questions are excluded from every rate.",
  unpromptedRate:
    "Share of answers to questions that don't name your brand which mention it anyway — whether AI brings you up on its own. This is the number that matters for discovery.",
  mentionRate:
    "Share of all tested answers that genuinely mention your brand. Answers that only say the AI couldn't find or doesn't know your brand don't count.",
  brandKnowledge:
    "For questions that name your brand: how many answers show the AI knows you, versus say it couldn't find or doesn't know you (detected from phrases like \"I couldn't find any information about…\").",
  citationRate:
    "Share of tested answers that cite your website as a source or link to it (any page on your domain or a subdomain).",
  competitorVisibility:
    "Share of the same tested answers that name each competitor. Only answers from one run are compared, so conditions are identical.",
  shareOfVoice:
    "Your brand's mentioning answers divided by the mentioning answers of all tracked brands (yours + competitors) in the run.",
  auditScore:
    "Weighted average of the website audit checks (0–100). Page-level checks score the fraction of crawled pages that pass.",
};
