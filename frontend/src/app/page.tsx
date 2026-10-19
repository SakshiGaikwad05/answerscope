import Link from "next/link";

const FEATURES = [
  {
    title: "Website audit",
    body: "Crawl your public pages (respecting robots.txt) and check titles, descriptions, headings, structured data, FAQ content, sitemaps and AI-crawler access.",
  },
  {
    title: "Customer questions",
    body: "Generate 20 realistic questions buyers ask AI assistants: best tools, alternatives, comparisons, pricing, features, use cases and beginner picks.",
  },
  {
    title: "AI visibility tests",
    body: "Ask a real AI provider each question and record whether it mentions your brand, cites your website, and which competitors it names — with evidence.",
  },
  {
    title: "Evidence-based recommendations",
    body: "Prioritized fixes tied to what was actually found: missing metadata, unanswered questions, comparison gaps and competitors that dominate answers.",
  },
];

const STEPS = [
  ["Create a project", "Enter your website, brand name, and optionally competitors and your category."],
  ["Run the audit", "We crawl a sample of your pages and score how answer-engine-ready they are."],
  ["Test AI answers", "With an API key configured, each question is sent to the provider and analyzed."],
  ["Act on findings", "Work through recommendations and re-run to track changes over time."],
];

export default function Home() {
  return (
    <div>
      <section className="border-b border-slate-200 bg-white">
        <div className="mx-auto max-w-5xl px-4 py-16 text-center sm:px-6 sm:py-24">
          <p className="text-sm font-semibold uppercase tracking-wide text-accent">Answer Engine Optimization</p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            Find out if AI assistants recommend your brand
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
            AnswerScope audits your website, asks AI the questions your customers ask, and shows — with evidence — where
            you&apos;re mentioned, where you&apos;re cited, and where competitors win instead.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/projects/new" className="rounded-lg bg-accent px-5 py-3 font-medium text-white hover:bg-accent-hover">
              Start an audit
            </Link>
            <Link href="/projects" className="rounded-lg border border-slate-300 bg-white px-5 py-3 font-medium text-slate-800 hover:bg-slate-50">
              View projects
            </Link>
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 className="text-2xl font-semibold text-slate-900">What you get</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <h3 className="font-semibold text-slate-900">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-600">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-14 sm:px-6">
        <h2 className="text-2xl font-semibold text-slate-900">How it works</h2>
        <ol className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STEPS.map(([title, body], i) => (
            <li key={title} className="rounded-xl border border-slate-200 bg-white p-5">
              <span className="grid h-8 w-8 place-items-center rounded-full bg-accent-soft text-sm font-semibold text-indigo-700">{i + 1}</span>
              <h3 className="mt-3 font-semibold text-slate-900">{title}</h3>
              <p className="mt-1 text-sm text-slate-600">{body}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-20 sm:px-6">
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-sm text-amber-900">
          <h2 className="font-semibold">Honest by design</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Every metric is computed from recorded answers. Nothing is simulated; if no provider is configured, visibility tests are disabled.</li>
            <li>API answers can differ from what consumer ChatGPT, Claude, Gemini or Perplexity show to a signed-in user.</li>
            <li>Recommendations improve how clearly your site answers questions. No change can guarantee AI citations or rankings.</li>
          </ul>
        </div>
      </section>
    </div>
  );
}
