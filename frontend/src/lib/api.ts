// Typed client for the FastAPI backend. Provider API keys live exclusively in
// the backend environment.
//
// By default requests go to the frontend's own origin (/api/...), which Next
// proxies to BACKEND_URL (see next.config.ts). Set NEXT_PUBLIC_API_URL only if
// the browser must call a separately hosted API directly (that API's
// CORS_ORIGINS must then include the frontend's origin).

/** Dispatched on window after login, sign-up and logout. */
export const AUTH_CHANGED_EVENT = "aeo-auth-changed";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "").replace(/\/$/, "");
const REQUEST_TIMEOUT_MS = 30_000;

export type JobStatus = "pending" | "running" | "completed" | "failed";

export interface Competitor {
  id: number;
  name: string;
  website_url: string | null;
}

export interface Project {
  id: number;
  brand_name: string;
  website_url: string;
  domain: string;
  industry: string | null;
  created_at: string;
  competitors: Competitor[];
}

export interface ProjectListItem extends Project {
  latest_audit_score: number | null;
  latest_brand_mention_rate: number | null;
  latest_unprompted_mention_rate: number | null;
  latest_activity: string;
}

export interface ProviderStatus {
  name: string;
  display_name: string;
  configured: boolean;
  model: string;
  setup_instructions: string | null;
  conditions: Record<string, unknown>;
}

export interface AuditSummary {
  id: number;
  project_id: number;
  status: JobStatus;
  progress_message: string | null;
  error: string | null;
  score: number | null;
  pages_crawled: number;
  created_at: string;
  completed_at: string | null;
}

export interface AuditCheck {
  id: string;
  label: string;
  category: string;
  weight: number;
  score: number;
  passed: boolean;
  detail: string;
  why: string;
  evidence: string[];
}

export interface PageIssue {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
}

export interface AuditPage {
  id: number;
  url: string;
  status_code: number | null;
  title: string | null;
  meta_description: string | null;
  canonical: string | null;
  lang: string | null;
  h1: string[];
  headings: { level: number; text: string }[];
  word_count: number;
  internal_links: number;
  external_links: number;
  schema_types: string[];
  has_faq: boolean;
  faq_questions: string[];
  issues: PageIssue[];
  text_excerpt: string | null;
}

export interface ContentGap {
  topic: string;
  label: string;
  example_question: string;
  covered: boolean;
  pages: string[];
}

export interface AuditDetail extends AuditSummary {
  site_info: {
    start_url?: string;
    root_url?: string;
    https?: boolean;
    robots?: {
      url?: string;
      found?: boolean;
      sitemaps?: string[];
      error?: string;
      ai_crawlers?: Record<string, { allowed: boolean; description: string }>;
    };
    sitemap?: { found?: boolean; url?: string | null; url_count?: number };
    failures?: { url: string; error: string }[];
    skipped_by_robots?: string[];
    schema_types?: string[];
    stopped_early?: string | null;
    js_rendered_shell?: boolean;
    js_rendered_pages?: string[];
    error?: { code: string; message: string; url: string | null; status_code: number | null };
  };
  checks: AuditCheck[];
  content_gaps: ContentGap[];
  pages: AuditPage[];
}

export interface Question {
  id: number;
  text: string;
  category: string;
  source: "llm" | "template";
  created_at: string;
}

export interface RunConditions {
  provider?: string;
  model?: string;
  effort?: string;
  web_search?: boolean;
  web_search_max_uses?: number;
  system_prompt?: string;
  brand?: string;
  domain?: string;
  competitors?: { id: number; name: string; domain: string | null }[];
  question_ids?: number[];
  [key: string]: unknown;
}

export interface RunSummary {
  id: number;
  project_id: number;
  provider: string;
  model: string;
  status: JobStatus;
  error: string | null;
  total_questions: number;
  completed_questions: number;
  conditions: RunConditions;
  created_at: string;
  completed_at: string | null;
}

export interface EntityStats {
  name: string;
  entity_type: "brand" | "competitor";
  answers_mentioning: number;
  answers_citing: number;
  mention_rate: number | null;
  citation_rate: number | null;
  share_of_voice: number | null;
}

export interface RunMetrics {
  unbranded_questions: number;
  unbranded_mentions: number;
  unbranded_mention_rate: number | null;
  branded_questions: number;
  branded_known: number;
  branded_known_rate: number | null;
  brand_unknown_answers: number;
  branded_unknown: number;
  total_questions: number;
  questions_tested: number;
  questions_failed: number;
  brand_mentions: number;
  website_citations: number;
  brand_mention_rate: number | null;
  website_citation_rate: number | null;
  answers_with_competitor_but_not_brand: number;
  entities: EntityStats[];
  by_category: {
    category: string;
    tested: number;
    brand_mentions: number;
    website_citations: number;
    mention_rate: number | null;
    citation_rate: number | null;
  }[];
}

export interface MentionEvidence {
  type: "snippet" | "cited_source" | "linked_in_answer";
  text?: string;
  matched?: string;
  url?: string;
  title?: string | null;
}

export interface Mention {
  entity_type: "brand" | "competitor";
  entity_name: string;
  kind: "mention" | "citation";
  occurrences: number;
  evidence: MentionEvidence[];
}

export interface Source {
  url: string;
  title?: string | null;
  type: "cited" | "search_result";
  cited_text?: string | null;
}

export interface Answer {
  id: number;
  question_id: number | null;
  question_text: string;
  question_category: string;
  provider: string;
  model: string;
  answer_text: string | null;
  sources: Source[];
  brand_mentioned: boolean;
  website_cited: boolean;
  error: string | null;
  latency_ms: number | null;
  created_at: string;
  mentions: Mention[];
  branded_question: boolean;
  brand_unknown: boolean;
  brand_unknown_evidence: string | null;
}

export interface RunDetail extends RunSummary {
  metrics: RunMetrics;
  answers: Answer[];
}

export type Level = "high" | "medium" | "low";
export type RecStatus = "open" | "planned" | "in_progress" | "completed" | "dismissed";

export interface Recommendation {
  id: number;
  key: string;
  audit_id: number | null;
  run_id: number | null;
  category: string;
  priority: Level; // impact
  effort: Level;
  confidence: Level;
  blocking: boolean;
  score: number;
  status: RecStatus;
  note: string | null;
  issue: string;
  why_it_matters: string;
  action: string;
  verify: string | null;
  evidence: string[];
  detected: boolean;
  first_detected_at: string;
  last_detected_at: string;
  resolved_at: string | null;
  status_updated_at: string | null;
  created_at: string;
  fix_available: boolean;
}

export interface Dashboard {
  project: Project;
  providers: ProviderStatus[];
  latest_audit: AuditSummary | null;
  latest_audit_checks: AuditCheck[];
  latest_run: RunSummary | null;
  latest_run_metrics: RunMetrics | null;
  recent_audits: AuditSummary[];
  recent_runs: RunSummary[];
  recommendation_counts: { high: number; medium: number; low: number };
  action_plan: Record<RecStatus | "no_longer_detected", number>;
  usage: Usage;
  active_question_count: number;
}

export interface User {
  id: number;
  email: string;
}

export interface UsageItem {
  used: number;
  limit: number;
  remaining: number;
}
export type Usage = Record<"visibility_run" | "question_generation" | "fix_generation", UsageItem>;

export interface FixDraft {
  id: number;
  recommendation_id: number;
  title: string;
  format: "markdown" | "html" | "json-ld" | "text";
  content: string;
  placeholders: string[];
  notes: string | null;
  sources: string[];
  generator: string; // "template" or the AI model
  created_at: string;
}

export interface CompareMetric {
  key: string;
  label: string;
  base: number | null;
  target: number | null;
  delta_pts: number | null;
  base_count?: number;
  target_count?: number;
  answers_changed?: number | null;
  may_be_noise: boolean;
}

export interface RunComparison {
  base: { id: number; created_at: string; model: string; questions_tested: number };
  target: { id: number; created_at: string; model: string; questions_tested: number };
  questions_compared: number;
  questions_only_in_base: number;
  questions_only_in_target: number;
  comparable: boolean;
  warnings: string[];
  one_answer_pts: number | null;
  metrics: CompareMetric[];
  entities: {
    name: string;
    entity_type: "brand" | "competitor";
    base_mention_rate: number | null;
    target_mention_rate: number | null;
    delta_pts: number | null;
  }[];
  question_changes: Record<"gained_mention" | "lost_mention" | "gained_citation" | "lost_citation" | "now_known" | "now_unknown", string[]>;
  competitor_changes: { question: string; gained: string[]; lost: string[] }[];
  unchanged_questions: number;
  resolved_between: { id: number; issue: string; resolved_at: string | null; status: string }[];
}

export class ApiError extends Error {
  status: number;
  setup?: string;
  code?: string;
  constructor(message: string, status: number, extra?: { setup?: string; code?: string }) {
    super(message);
    this.status = status;
    this.setup = extra?.setup;
    this.code = extra?.code;
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs: number = REQUEST_TIMEOUT_MS): Promise<T> {
  let res: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") {
      throw new ApiError(`The API did not respond within ${timeoutMs / 1000} seconds. Please try again.`, 0);
    }
    throw new ApiError(`Cannot reach the API${API_URL ? ` at ${API_URL}` : ""}. Is the backend running?`, 0);
  } finally {
    clearTimeout(timer);
  }
  // Session missing or expired: send the user to log in, then back here.
  if (res.status === 401 && !path.startsWith("/api/auth/") && typeof window !== "undefined") {
    const next = encodeURIComponent(window.location.pathname + window.location.search);
    // A full navigation (not router.push) is intended: this helper runs outside React, and
    // reloading clears any state that belonged to the expired session.
    // eslint-disable-next-line @next/next/no-location-assign-relative-destination
    window.location.assign(`/login?next=${next}`);
    throw new ApiError("Please log in to continue", 401);
  }
  if (res.status === 204) return undefined as T;
  // When the backend is down, the Next /api proxy answers 500 with an empty body and no
  // content type (a real backend error always carries one).
  if (!API_URL && res.status >= 500 && !res.headers.get("content-type")) {
    throw new ApiError("Cannot reach the backend API. Is it running (uvicorn on port 8000)?", res.status);
  }
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const detail = (body as { detail?: unknown })?.detail;
    if (detail && typeof detail === "object" && "message" in detail) {
      const d = detail as { message: string; setup?: string; code?: string };
      throw new ApiError(d.message, res.status, { setup: d.setup, code: d.code });
    }
    throw new ApiError(typeof detail === "string" ? detail : `Request failed (HTTP ${res.status})`, res.status);
  }
  return body as T;
}

export const api = {
  me: () => request<User>("/api/auth/me"),
  register: (email: string, password: string) =>
    request<User>("/api/auth/register", { method: "POST", body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ email, password }) }),
  logout: () => request<void>("/api/auth/logout", { method: "POST" }),
  usage: () => request<Usage>("/api/usage"),
  listFixes: (recId: number) => request<FixDraft[]>(`/api/recommendations/${recId}/fixes`),
  createFix: (recId: number) =>
    request<FixDraft>(`/api/recommendations/${recId}/fixes`, { method: "POST" }, 120_000),
  providers: () => request<ProviderStatus[]>("/api/providers"),
  categories: () => request<Record<string, string>>("/api/meta/question-categories"),
  listProjects: () => request<ProjectListItem[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (body: {
    website_url: string;
    brand_name: string;
    industry?: string;
    competitors: { name: string; website_url?: string }[];
  }) => request<Project>("/api/projects", { method: "POST", body: JSON.stringify(body) }),
  updateProject: (id: number, body: { industry?: string | null; competitors: { name: string; website_url?: string | null }[] }) =>
    request<Project>(`/api/projects/${id}`, { method: "PUT", body: JSON.stringify(body) }),
  deleteProject: (id: number) => request<void>(`/api/projects/${id}`, { method: "DELETE" }),
  dashboard: (id: number) => request<Dashboard>(`/api/projects/${id}/dashboard`),
  startAudit: (id: number) => request<AuditSummary>(`/api/projects/${id}/audits`, { method: "POST" }),
  listAudits: (id: number) => request<AuditSummary[]>(`/api/projects/${id}/audits`),
  getAudit: (auditId: number) => request<AuditDetail>(`/api/audits/${auditId}`),
  generateQuestions: (id: number) =>
    request<{ questions: Question[]; source: string; note: string | null }>(`/api/projects/${id}/questions/generate`, {
      method: "POST",
    }),
  listQuestions: (id: number) => request<Question[]>(`/api/projects/${id}/questions`),
  startRun: (id: number, provider = "anthropic") =>
    request<RunSummary>(`/api/projects/${id}/runs`, { method: "POST", body: JSON.stringify({ provider }) }),
  listRuns: (id: number) => request<RunSummary[]>(`/api/projects/${id}/runs`),
  getRun: (runId: number) => request<RunDetail>(`/api/runs/${runId}`),
  retestRun: (runId: number) => request<RunSummary>(`/api/runs/${runId}/retest`, { method: "POST" }),
  compareRuns: (projectId: number, base: number, target: number) =>
    request<RunComparison>(`/api/projects/${projectId}/compare?base=${base}&target=${target}`),
  recommendations: (id: number) => request<Recommendation[]>(`/api/projects/${id}/recommendations`),
  updateRecommendation: (recId: number, body: { status?: RecStatus; note?: string | null }) =>
    request<Recommendation>(`/api/recommendations/${recId}`, { method: "PATCH", body: JSON.stringify(body) }),
};
