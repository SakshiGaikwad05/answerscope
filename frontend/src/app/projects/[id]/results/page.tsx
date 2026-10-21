"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";

import { useProject } from "@/components/ProjectContext";
import { ProviderNotConfigured, RunConditionsNote } from "@/components/ProviderNotice";
import { Badge, Card, EmptyState, ErrorState, Loading, StatusBadge } from "@/components/ui";
import { api, type Answer, type Question, type RunDetail, type RunSummary } from "@/lib/api";
import { CATEGORY_LABELS, dateTime, isActive, pct, shortUrl } from "@/lib/format";

function YesNo({ yes, yesLabel, noLabel }: { yes: boolean; yesLabel: string; noLabel: string }) {
  return yes ? <Badge tone="good">✓ {yesLabel}</Badge> : <Badge tone="neutral">✕ {noLabel}</Badge>;
}

function AnswerRow({ a }: { a: Answer }) {
  const competitors = [...new Set(a.mentions.filter((m) => m.entity_type === "competitor" && m.kind === "mention").map((m) => m.entity_name))];
  const cited = a.sources.filter((s) => s.type === "cited");
  const searched = a.sources.filter((s) => s.type === "search_result");
  return (
    <li className="py-3">
      <details>
        <summary className="grid cursor-pointer list-none gap-2 md:grid-cols-[1fr_9rem_9rem_12rem] md:items-center">
          <span>
            <span className="font-medium text-slate-900">{a.question_text}</span>
            <span className="mt-0.5 block text-xs text-slate-500">
              {CATEGORY_LABELS[a.question_category] ?? a.question_category}
              {a.branded_question && <Badge className="ml-2">names you</Badge>}
              {a.position != null && <Badge tone="accent" className="ml-2">#{a.position} of {a.listed} listed</Badge>}
              {a.position == null && a.listed != null && <Badge className="ml-2">not in list of {a.listed}</Badge>}
              {a.location_mentioned === true && <Badge className="ml-2">mentions your area</Badge>}
            </span>
          </span>
          {a.error ? (
            <span className="md:col-span-3"><Badge tone="bad">✕ failed</Badge> <span className="text-sm text-rose-700">{a.error}</span></span>
          ) : (
            <>
              <span>
                {a.brand_unknown ? (
                  <Badge tone="warning">⚠ doesn&apos;t know you</Badge>
                ) : (
                  <YesNo yes={a.brand_mentioned} yesLabel="mentioned" noLabel="not mentioned" />
                )}
              </span>
              <span><YesNo yes={a.website_cited} yesLabel="cited" noLabel="not cited" /></span>
              <span className="text-sm text-slate-600">{competitors.length ? competitors.join(", ") : <span className="text-slate-400">no competitors</span>}</span>
            </>
          )}
        </summary>
        {!a.error && (
          <div className="mt-3 grid gap-4 rounded-lg bg-slate-50 p-4 lg:grid-cols-2">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Answer · {a.provider} / <span className="font-mono normal-case">{a.model}</span> · {dateTime(a.created_at)}
              </p>
              <div className="mt-2 max-h-96 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-slate-800">{a.answer_text}</div>
            </div>
            <div className="space-y-4 text-sm">
              <div>
                {a.recommended_businesses && a.recommended_businesses.length > 0 && (
                  <div className="mb-3">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Businesses recommended, in order <Badge tone="warning">AI-extracted</Badge></p>
                    <ol className="mt-1 list-decimal pl-5 text-slate-700">{a.recommended_businesses.map((b) => <li key={b.name}>{b.name}</li>)}</ol>
                  </div>
                )}
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Detection evidence</p>
                {a.brand_unknown && (
                  <div className="mt-1 rounded border border-amber-200 bg-amber-50 p-2 text-amber-900">
                    <p className="font-medium">The AI says it doesn&apos;t know your brand — not counted as a mention</p>
                    <p className="mt-1"><q>{a.brand_unknown_evidence}</q></p>
                  </div>
                )}
                {a.mentions.length === 0 ? (
                  <p className="mt-1 text-slate-500">No tracked brand was mentioned or cited.</p>
                ) : (
                  <ul className="mt-1 space-y-2">
                    {a.mentions.map((m) => (
                      <li key={m.entity_name + m.kind} className="rounded border border-slate-200 bg-white p-2">
                        <p className="font-medium text-slate-800">
                          {m.entity_name} {m.entity_type === "brand" && <Badge tone="accent">you</Badge>} — {m.kind === "mention" ? `mentioned ${m.occurrences}×` : `cited (${m.occurrences})`}
                        </p>
                        <ul className="mt-1 space-y-1 text-slate-600">
                          {m.evidence.map((e, i) => (
                            <li key={i} className="break-words">
                              {e.type === "snippet" ? <q>{e.text}</q> : (
                                <>
                                  {e.type === "cited_source" ? "Cited source: " : "Linked in answer: "}
                                  <a href={e.url} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:underline break-all">{e.url}</a>
                                </>
                              )}
                            </li>
                          ))}
                        </ul>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Sources cited by the provider ({cited.length})</p>
                {cited.length === 0 ? <p className="mt-1 text-slate-500">None.</p> : (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {cited.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noopener noreferrer" className="text-indigo-700 hover:underline break-all">{s.title || shortUrl(s.url)}</a></li>)}
                  </ul>
                )}
                {searched.length > 0 && (
                  <p className="mt-1 text-xs text-slate-500">
                    Also retrieved by web search but not cited: {searched.slice(0, 8).map((s) => shortUrl(s.url)).join(", ")}{searched.length > 8 ? "…" : ""}
                  </p>
                )}
              </div>
            </div>
          </div>
        )}
      </details>
    </li>
  );
}

function ResultsView() {
  const { projectId, dashboard } = useProject();
  const search = useSearchParams();
  const router = useRouter();
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [questions, setQuestions] = useState<Question[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [category, setCategory] = useState("all");
  const [filter, setFilter] = useState(() => search.get("show") || "all");

  const latestJob = dashboard?.recent_runs[0];
  const selectedId = Number(search.get("run")) || dashboard?.latest_run?.id || (latestJob && isActive(latestJob.status) ? latestJob.id : null);

  useEffect(() => {
    Promise.all([api.listRuns(projectId), api.listQuestions(projectId)])
      .then(([r, q]) => { setRuns(r); setQuestions(q); })
      .catch((e: Error) => setError(e.message));
  }, [projectId, latestJob?.status, latestJob?.id, dashboard?.active_question_count]);

  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    api.getRun(selectedId).then((r) => !cancelled && setRun(r)).catch((e: Error) => !cancelled && setError(e.message));
    return () => { cancelled = true; };
  }, [selectedId, latestJob?.status, latestJob?.completed_questions]);

  const answers = useMemo(() => {
    if (!run) return [];
    return run.answers.filter((a) => {
      if (category !== "all" && a.question_category !== category) return false;
      if (filter === "mentioned") return !a.error && a.brand_mentioned && !a.brand_unknown;
      if (filter === "not_mentioned") return !a.error && (!a.brand_mentioned || a.brand_unknown);
      if (filter === "unknown") return !a.error && a.brand_unknown;
      if (filter === "unbranded") return !a.error && !a.branded_question;
      if (filter === "cited") return !a.error && a.website_cited;
      if (filter === "competitor_only") return !a.error && !a.brand_mentioned && a.mentions.some((m) => m.entity_type === "competitor" && m.kind === "mention");
      if (filter === "failed") return Boolean(a.error);
      return true;
    });
  }, [run, category, filter]);

  if (error) return <ErrorState message={error} />;
  if (!dashboard || runs === null || questions === null) return <Loading />;

  return (
    <div className="space-y-6">
      <ProviderNotConfigured providers={dashboard.providers} />

      {runs.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <label htmlFor="run-select" className="text-slate-600">Visibility test</label>
          <select
            id="run-select"
            value={selectedId ?? ""}
            onChange={(e) => router.replace(`/projects/${projectId}/results?run=${e.target.value}`)}
            className="rounded-lg border border-slate-300 bg-white px-3 py-1.5"
          >
            {runs.map((r) => (
              <option key={r.id} value={r.id}>Run #{r.id} · {dateTime(r.created_at)} · {r.model} · {r.status}</option>
            ))}
          </select>
        </div>
      )}

      {!selectedId ? (
        <Card title="Generated questions" description="These are tested against the AI provider when you run a visibility test.">
          {questions.length === 0 ? (
            <EmptyState title="No questions yet" description="Generate questions from the Dashboard tab." />
          ) : (
            <QuestionList questions={questions} />
          )}
        </Card>
      ) : !run || run.id !== selectedId ? (
        <Loading label="Loading results…" />
      ) : (
        <>
          {isActive(run.status) && (
            <div role="status" className="flex items-center gap-3 rounded-xl border border-indigo-200 bg-indigo-50 p-4 text-sm text-indigo-900">
              <StatusBadge status={run.status} /> {run.completed_questions} of {run.total_questions} questions answered. Results appear as they arrive.
            </div>
          )}
          {run.status === "failed" && <ErrorState message={`Run #${run.id} failed: ${run.error}`} />}
          <Card
            title={`Question-by-question results (${run.answers.length})`}
            description={
              <>
                Unprompted: mentioned in {run.metrics.unbranded_mentions} of {run.metrics.unbranded_questions} answers to questions that don&apos;t name you ({pct(run.metrics.unbranded_mention_rate)}).
                {run.metrics.branded_questions > 0 && (
                  <> Questions naming you: AI knew you in {run.metrics.branded_known} of {run.metrics.branded_questions}{run.metrics.branded_unknown > 0 && <>, said it couldn&apos;t find you in {run.metrics.branded_unknown}</>}.</>
                )}{" "}
                Website cited in {run.metrics.website_citations} of {run.metrics.questions_tested} ({pct(run.metrics.website_citation_rate)}).
              </>
            }
          >
            <RunConditionsNote conditions={run.conditions} when={dateTime(run.created_at)} />
            <div className="mt-4 flex flex-wrap gap-3 text-sm">
              <label className="flex items-center gap-2">
                <span className="text-slate-600">Category</span>
                <select value={category} onChange={(e) => setCategory(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1">
                  <option value="all">All</option>
                  {Object.entries(CATEGORY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
              </label>
              <label className="flex items-center gap-2">
                <span className="text-slate-600">Show</span>
                <select value={filter} onChange={(e) => setFilter(e.target.value)} className="rounded-lg border border-slate-300 bg-white px-2 py-1">
                  <option value="all">All answers</option>
                  <option value="mentioned">Brand mentioned</option>
                  <option value="not_mentioned">Brand not mentioned</option>
                  <option value="unknown">AI doesn&apos;t know brand</option>
                  <option value="unbranded">Questions that don&apos;t name you</option>
                  <option value="cited">Website cited</option>
                  <option value="competitor_only">Competitor mentioned, brand not</option>
                  <option value="failed">Failed questions</option>
                </select>
              </label>
            </div>
            <div className="mt-4 hidden border-b border-slate-200 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-500 md:grid md:grid-cols-[1fr_9rem_9rem_12rem]">
              <span>Question</span><span>Brand</span><span>Website</span><span>Competitors mentioned</span>
            </div>
            {answers.length === 0 ? (
              <p className="py-6 text-center text-sm text-slate-500">{run.answers.length ? "No answers match these filters." : "No answers recorded yet."}</p>
            ) : (
              <ul className="divide-y divide-slate-100">{answers.map((a) => <AnswerRow key={a.id} a={a} />)}</ul>
            )}
            <p className="mt-3 text-xs text-slate-500">Click a question to read the full answer, the detection evidence and the sources.</p>
          </Card>
          <Card title="Current question set" description="Questions used for the next visibility test">
            <QuestionList questions={questions} />
          </Card>
        </>
      )}
    </div>
  );
}

function QuestionList({ questions }: { questions: Question[] }) {
  if (questions.length === 0) return <p className="text-sm text-slate-500">No questions yet.</p>;
  return (
    <ol className="list-decimal space-y-1.5 pl-6 text-sm">
      {questions.map((q) => (
        <li key={q.id} className="text-slate-800">
          {q.text}{" "}
          <span className="text-xs text-slate-500">· {CATEGORY_LABELS[q.category] ?? q.category}</span>{" "}
          <Badge tone={q.source === "llm" ? "accent" : "neutral"}>{q.source === "llm" ? "AI-generated" : "template"}</Badge>
        </li>
      ))}
    </ol>
  );
}

export default function ResultsPage() {
  return (
    <Suspense fallback={<Loading />}>
      <ResultsView />
    </Suspense>
  );
}
