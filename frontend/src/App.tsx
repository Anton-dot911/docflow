import { DemoPage } from "./pages/DemoPage.tsx";
import { HistoryPage } from "./pages/HistoryPage.tsx";
import { ReviewPage } from "./pages/ReviewPage.tsx";

// T8 adds the History page as the default view (replacing T1's health-check
// skeleton, which was only ever a placeholder until Upload/History existed —
// see docs/decisions.md). The Review page is still reached via ?id=; T9 adds
// /demo. No router dependency — both are plain window.location checks until
// an Upload page needs real routing.
export function App() {
  const documentId = new URLSearchParams(window.location.search).get("id");
  const isDemoPage = window.location.pathname === "/demo";

  if (documentId) {
    return <ReviewPage documentId={documentId} />;
  }

  if (isDemoPage) {
    return <DemoPage />;
  }

  return <HistoryPage />;
}
