import { useEffect, useState } from "react";
import type { HealthResponse } from "./api/schemas.ts";
import { fetchHealth } from "./api/client.ts";
import { ReviewPage } from "./pages/ReviewPage.tsx";

const PROJECT_NAME = "DocFlow";

// Skeleton page; replaced by the Upload/History/Demo pages in later tasks.
// T7 adds the Review page, reached via ?id=<document_id> until routing and
// an Upload/History page exist to link into it.
export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const documentId = new URLSearchParams(window.location.search).get("id");

  useEffect(() => {
    if (documentId) return;
    fetchHealth()
      .then(setHealth)
      .catch((cause: unknown) => {
        setError(cause instanceof Error ? cause.message : String(cause));
      });
  }, [documentId]);

  if (documentId) {
    return <ReviewPage documentId={documentId} />;
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 bg-slate-50">
      <h1 className="text-3xl font-bold text-slate-900">{PROJECT_NAME}</h1>
      <p className="text-slate-600">
        backend status:{" "}
        {health !== null ? (
          <span className="font-mono text-green-700">
            {health.status} @ {health.commit.slice(0, 7)}
          </span>
        ) : error !== null ? (
          <span className="font-mono text-red-700">{error}</span>
        ) : (
          <span className="font-mono text-slate-400">loading…</span>
        )}
      </p>
      <p className="text-sm text-slate-400">
        Open a document for review with <code>?id=&lt;document_id&gt;</code>
      </p>
    </main>
  );
}
