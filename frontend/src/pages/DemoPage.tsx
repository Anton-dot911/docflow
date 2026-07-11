import { useEffect, useState } from "react";
import { fetchDemoSamples } from "../api/demo.ts";
import { exportUrl } from "../api/history.ts";
import type { DemoSample } from "../api/schemas.ts";

// T9 demo entry page: pitch + the 5 curated documents + a "how it works"
// strip. No auth; cards open the existing Review page via `?id=` (T7), reused
// as-is since demo documents are ordinary rows in the same tables (see
// docs/decisions.md) — the Review UI itself needs no demo-specific code.
// Confirmed cards additionally expose T8's JSON/CSV download links, same
// `exportUrl()` helper and 409-if-not-confirmed gating as the History page.

const HOW_IT_WORKS = ["Завантаження", "Екстракція", "Перевірка", "Експорт"];

function statusLabel(status: DemoSample["status"]): string {
  switch (status) {
    case "confirmed":
      return "підтверджено";
    case "review":
      return "готово до перевірки";
    case "processing":
      return "обробляється…";
    case "failed":
      return "помилка обробки";
    default:
      return "ще не завантажено";
  }
}

function DemoCard({ sample }: { sample: DemoSample }) {
  const confirmed = sample.status === "confirmed";
  const open = () => {
    window.location.href = `?id=${sample.id}`;
  };

  return (
    <div
      className="block rounded-lg border border-slate-200 bg-white p-4 shadow-sm transition hover:border-slate-400 hover:shadow-md"
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        }
      }}
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="font-semibold text-slate-900">{sample.title}</h3>
        <span className="whitespace-nowrap rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-600">
          {sample.difficulty}
        </span>
      </div>
      <p className="mt-1 text-sm text-slate-600">{sample.description}</p>
      <div className="mt-3 flex items-center justify-between">
        <p className="text-xs text-slate-400">{statusLabel(sample.status)}</p>
        {confirmed && (
          <div className="flex gap-2">
            <a
              className="text-xs font-medium text-slate-600 underline hover:text-slate-900"
              href={exportUrl(sample.id, "json")}
              download
              onClick={(event) => event.stopPropagation()}
            >
              JSON
            </a>
            <a
              className="text-xs font-medium text-slate-600 underline hover:text-slate-900"
              href={exportUrl(sample.id, "csv")}
              download
              onClick={(event) => event.stopPropagation()}
            >
              CSV
            </a>
          </div>
        )}
      </div>
    </div>
  );
}

export function DemoPage() {
  const [samples, setSamples] = useState<DemoSample[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchDemoSamples()
      .then((data) => {
        if (!cancelled) setSamples(data);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : String(cause));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 px-6 py-10 text-slate-900">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-3xl font-bold">DocFlow — демо без реєстрації</h1>
        <p className="mt-2 text-lg text-slate-600">
          Завантажте рахунок — і за секунди отримайте структуровані дані, перевірені та готові до
          експорту.
        </p>

        <ol className="mt-8 flex flex-wrap items-center gap-2 text-sm text-slate-600">
          {HOW_IT_WORKS.map((step, i) => (
            <li key={step} className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs font-semibold text-white">
                {i + 1}
              </span>
              {step}
              {i < HOW_IT_WORKS.length - 1 && <span className="text-slate-300">→</span>}
            </li>
          ))}
        </ol>

        <h2 className="mt-10 text-xl font-semibold">5 прикладів різної складності</h2>

        {error !== null && <p className="mt-4 font-mono text-red-700">{error}</p>}
        {samples === null && error === null && <p className="mt-4 text-slate-400">завантаження…</p>}

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          {samples?.map((sample) => (
            <DemoCard key={sample.id} sample={sample} />
          ))}
        </div>
      </div>
    </main>
  );
}
