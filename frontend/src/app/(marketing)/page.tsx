import Link from "next/link";
import { FOCUS_RING } from "@/components/styles";

const FEATURES = [
  {
    title: "Centralized documents",
    body: "Keep company documents in one organized, searchable place.",
  },
  {
    title: "AI-assisted insight",
    body: "Extract meaning and answers from your documents with AI.",
  },
  {
    title: "Built for teams",
    body: "Designed around secure, controlled access for your organization.",
  },
];

export default function HomePage() {
  return (
    <>
      <section className="mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-28">
        <p className="text-sm font-semibold uppercase tracking-wide text-indigo-600">
          Document management
        </p>
        <h1 className="mt-3 max-w-3xl text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
          Your documents, organized and understood by AI.
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-slate-600">
          Metriks AI is a document management platform that helps teams store,
          find and make sense of their business documents.
        </p>
        <div className="mt-8">
          <Link
            href="/dashboard"
            className={`inline-block rounded-md bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-indigo-700 ${FOCUS_RING}`}
          >
            Open dashboard
          </Link>
        </div>
      </section>

      <section
        aria-labelledby="features-heading"
        className="border-t border-slate-200 bg-white"
      >
        <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
          <h2 id="features-heading" className="sr-only">
            Features
          </h2>
          <ul className="grid gap-8 md:grid-cols-3">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <h3 className="font-semibold text-slate-900">{f.title}</h3>
                <p className="mt-2 text-sm text-slate-600">{f.body}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </>
  );
}
