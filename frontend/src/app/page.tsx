import Link from "next/link";

const ASSISTANTS = ["ChatGPT", "Claude", "Gemini", "Perplexity"];

const CHECKS = [
  {
    title: "Can AI crawlers read your site?",
    body: "We fetch your pages the way AI crawlers do, without running JavaScript, and show what they actually receive: real text, or an empty app shell.",
  },
  {
    title: "Is your business information clear?",
    body: "Name, city, service area, address, phone, hours and services: we check they're on your website, consistent, and marked up as LocalBusiness data.",
  },
  {
    title: "Do assistants mention you?",
    body: "We ask ChatGPT, Claude, Gemini and Perplexity the questions local customers ask, and record who they recommend, with the exact answer as evidence.",
  },
  {
    title: "Where can you earn mentions?",
    body: "Legitimate local directories, associations, news sites and suppliers, each page loaded and checked. No paid links, no spam, no made-up authority scores.",
  },
];

const STEPS = [
  ["Add your business", "Your website, business name, city and services. Takes a minute."],
  ["Run the free audit", "Technical, content and local SEO checks, each with evidence and a suggested fix."],
  ["Test AI assistants", "Connect your own API keys and ask each assistant the same 20 local questions."],
  ["Fix and retest", "Work through a prioritized plan, then retest and compare each assistant before and after."],
];

export default function Home() {
  return (
    <div>
      <section className="relative overflow-hidden border-b border-slate-200 bg-white">
        <div aria-hidden="true" className="pointer-events-none absolute inset-x-0 -top-40 h-80 bg-gradient-to-b from-indigo-50 to-transparent" />
        <div className="relative mx-auto max-w-5xl px-4 py-16 text-center sm:px-6 sm:py-24">
          <p className="inline-flex items-center gap-2 rounded-full border border-indigo-100 bg-accent-soft px-3 py-1 text-xs font-semibold text-indigo-700">
            AI visibility for local businesses
          </p>
          <h1 className="mt-5 text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl">
            When customers ask AI for a business like yours, are you in the answer?
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg leading-relaxed text-slate-600">
            AnswerScope checks whether AI assistants can read your website, whether your local details are clear, and
            whether {ASSISTANTS.slice(0, -1).join(", ")} and {ASSISTANTS.at(-1)} mention you. Then it gives you a fix list with evidence for every item.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Link href="/projects/new" className="rounded-lg bg-accent px-5 py-3 font-medium text-white shadow-sm hover:bg-accent-hover">
              Run a free website audit
            </Link>
            <Link href="/projects" className="rounded-lg border border-slate-300 bg-white px-5 py-3 font-medium text-slate-800 hover:bg-slate-50">
              Your projects
            </Link>
          </div>
          <p className="mt-4 text-xs text-slate-500">The audit is free. AI assistant tests use your own API keys, so you only pay your provider.</p>
          <ul className="mt-10 flex flex-wrap justify-center gap-2" aria-label="Assistants you can test">
            {ASSISTANTS.map((a) => (
              <li key={a} className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 shadow-sm">{a}</li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <h2 className="text-2xl font-semibold text-slate-900">Four questions, answered with evidence</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2">
          {CHECKS.map((f, i) => (
            <div key={f.title} className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
              <span className="text-xs font-semibold tabular-nums text-indigo-600">0{i + 1}</span>
              <h3 className="mt-1 font-semibold text-slate-900">{f.title}</h3>
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
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
            <h2 className="font-semibold text-slate-900">Honest by design</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Every number comes from a recorded answer or a page we fetched. Nothing is simulated or estimated without a label.</li>
              <li>API answers can differ from what the ChatGPT, Claude, Gemini or Perplexity apps show to a signed-in person.</li>
              <li>No tool can guarantee that an AI assistant will recommend your business. We show what helps and measure what changes.</li>
            </ul>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-6 text-sm text-slate-600">
            <h2 className="font-semibold text-slate-900">Your keys, your costs</h2>
            <ul className="mt-2 list-disc space-y-1 pl-5">
              <li>Add only the assistants you want to test. Google Gemini offers a free tier.</li>
              <li>Keys are encrypted, used only for your tests, and never shown again after saving.</li>
              <li>We never change your website. Every fix is a draft for you to review.</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}
