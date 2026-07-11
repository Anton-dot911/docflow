import { HistoryPage } from "./pages/HistoryPage.tsx";
import { ReviewPage } from "./pages/ReviewPage.tsx";

// T8 adds the History page as the default view (replacing T1's health-check
// skeleton, which was only ever a placeholder until Upload/History existed —
// see docs/decisions.md). The Review page is still reached via ?id=
// (no router yet).
export function App() {
  const documentId = new URLSearchParams(window.location.search).get("id");

  if (documentId) {
    return <ReviewPage documentId={documentId} />;
  }

  return <HistoryPage />;
}
