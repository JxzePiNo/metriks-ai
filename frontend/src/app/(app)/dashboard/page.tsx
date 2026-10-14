import type { Metadata } from "next";

export const metadata: Metadata = { title: "Documents" };

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Documents
        </h1>
        <button
          type="button"
          disabled
          className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
        >
          Upload document
        </button>
      </div>

      <section
        aria-labelledby="empty-heading"
        className="mt-8 rounded-lg border border-dashed border-slate-300 bg-white px-6 py-16 text-center"
      >
        <h2 id="empty-heading" className="text-lg font-semibold text-slate-900">
          No documents yet
        </h2>
        <p className="mx-auto mt-2 max-w-md text-sm text-slate-600">
          Documents you add will appear here. Uploading will be available once
          the backend is connected.
        </p>
      </section>
    </div>
  );
}
