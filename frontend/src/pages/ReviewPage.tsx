import { useEffect, useMemo, useState } from "react";
import {
  ConfirmConflictError,
  confirmDocument,
  fetchDocument,
  fetchDocumentFileUrl,
  patchExtraction,
} from "../api/review.ts";
import type { DocumentDetail } from "../api/schemas.ts";
import { fieldDomId } from "../components/Field.tsx";
import { FieldsPane } from "../components/FieldsPane.tsx";
import { DocumentPane, type HighlightRequest } from "../components/DocumentPane.tsx";
import { ThemeSwitch, type Theme } from "../components/ThemeSwitch.tsx";
import { canConfirm } from "../state/confirmGate.ts";
import { getFieldValue } from "../state/fieldPath.ts";
import { flagsFor } from "../state/flags.ts";
import { nextUnresolvedPath } from "../state/guidedNav.ts";
import { initReviewState, reviewReducer, type ReviewState } from "../state/reviewReducer.ts";
import "./review.css";

interface ReviewPageProps {
  documentId: string;
}

const DESKTOP_BREAKPOINT = "(min-width: 880px)";

function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(() => window.matchMedia(DESKTOP_BREAKPOINT).matches);
  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_BREAKPOINT);
    const listener = () => setIsDesktop(mql.matches);
    mql.addEventListener("change", listener);
    return () => mql.removeEventListener("change", listener);
  }, []);
  return isDesktop;
}

function isImageFilename(filename: string): boolean {
  return /\.(jpe?g|png)$/i.test(filename);
}

function scrollToField(path: string): void {
  document
    .getElementById(fieldDomId(path))
    ?.scrollIntoView({ behavior: "smooth", block: "center" });
}

export function ReviewPage({ documentId }: ReviewPageProps) {
  const [theme, setTheme] = useState<Theme>(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  const [doc, setDoc] = useState<DocumentDetail | null>(null);
  const [fileUrl, setFileUrl] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reviewState, setReviewState] = useState<ReviewState | null>(null);
  const [openPath, setOpenPath] = useState<string | null>(null);
  const [highlightFound, setHighlightFound] = useState<boolean | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const isDesktop = useIsDesktop();

  useEffect(() => {
    let cancelled = false;
    fetchDocument(documentId)
      .then((detail) => {
        if (cancelled) return;
        setDoc(detail);
        if (detail.extraction) setReviewState(initReviewState(detail.extraction));
      })
      .catch((cause: unknown) => {
        if (!cancelled) setLoadError(cause instanceof Error ? cause.message : String(cause));
      });
    fetchDocumentFileUrl(documentId)
      .then((res) => {
        if (!cancelled) setFileUrl(res.url);
      })
      .catch(() => undefined); // the fields pane still works without a rendered document
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  const flags = useMemo(
    () =>
      reviewState
        ? flagsFor(
            reviewState.extraction.field_confidences,
            reviewState.extraction.validation_issues,
          )
        : [],
    [reviewState],
  );
  const flagByPath = useMemo(() => new Map(flags.map((f) => [f.path, f])), [flags]);
  const unresolvedCount = flags.filter((f) => f.severity !== "ok").length;
  const allResolved = canConfirm(flags);

  const documentSearchable = doc?.mode === "text" && !isImageFilename(doc.filename);
  const showSnippetDrawer = !isDesktop || !documentSearchable || highlightFound === false;

  const activeFlag = openPath ? flagByPath.get(openPath) : undefined;
  const highlight: HighlightRequest | null =
    activeFlag && activeFlag.sourceSnippet
      ? { snippet: activeFlag.sourceSnippet, severity: activeFlag.severity }
      : null;

  function toggleField(path: string) {
    setOpenPath((current) => (current === path ? null : path));
    setHighlightFound(null);
  }

  async function submitEdit(path: string, newValue: string) {
    if (!reviewState) return;
    setReviewState(
      (prev) => prev && reviewReducer(prev, { type: "edit/start", path, value: newValue }),
    );
    try {
      const updated = await patchExtraction(reviewState.extraction.id, path, newValue);
      setReviewState(
        (prev) => prev && reviewReducer(prev, { type: "edit/success", extraction: updated }),
      );
      setOpenPath(null);
    } catch (cause) {
      setReviewState(
        (prev) =>
          prev &&
          reviewReducer(prev, {
            type: "edit/failure",
            message: cause instanceof Error ? cause.message : String(cause),
          }),
      );
    }
  }

  function acceptAsIs(path: string) {
    if (!reviewState) return;
    const current = getFieldValue(
      reviewState.extraction.payload as unknown as Record<string, unknown>,
      path,
    );
    void submitEdit(path, current === null || current === undefined ? "" : String(current));
  }

  function goToNextField() {
    const next = nextUnresolvedPath(flags, openPath);
    if (next === null) return;
    setOpenPath(next);
    setHighlightFound(null);
    scrollToField(next);
  }

  async function confirm() {
    setConfirmError(null);
    setConfirming(true);
    try {
      await confirmDocument(documentId);
      setDoc((prev) => prev && { ...prev, status: "confirmed" });
      setToast("Документ підтверджено ✓");
      setTimeout(() => setToast(null), 2200);
    } catch (cause) {
      if (cause instanceof ConfirmConflictError) {
        setConfirmError(`Ще є непідтверджені поля: ${cause.conflict.unresolved_fields.join(", ")}`);
      } else {
        setConfirmError(cause instanceof Error ? cause.message : String(cause));
      }
    } finally {
      setConfirming(false);
    }
  }

  if (loadError) {
    return (
      <div className="rv-app" data-theme={theme}>
        <div className="rv-wrap">
          <p role="alert">Не вдалося завантажити документ: {loadError}</p>
        </div>
      </div>
    );
  }

  if (!doc) {
    return (
      <div className="rv-app" data-theme={theme}>
        <div className="rv-wrap">
          <p>Завантаження…</p>
        </div>
      </div>
    );
  }

  const confirmed = doc.status === "confirmed";
  const confirmReady = allResolved && !confirmed;

  return (
    <div className="rv-app" data-theme={theme}>
      <div className="rv-wrap">
        <ThemeSwitch theme={theme} onChange={setTheme} />

        <div className="rv-header">
          <span className="rv-logo" aria-hidden="true">
            Df
          </span>
          <div className="rv-header__meta">
            <h1 className="rv-header__title">{doc.filename}</h1>
            <div className="rv-header__sub">
              {doc.doc_type ?? "документ"} · {new Date(doc.created_at).toLocaleString("uk-UA")}
            </div>
          </div>
          <span className={`rv-badge ${confirmed ? "rv-badge--confirmed" : ""}`}>
            {confirmed ? "підтверджено" : "на перевірці"}
          </span>
          <div className="rv-header__actions">
            <button type="button" className="rv-btn rv-btn--ghost" onClick={goToNextField}>
              Наступне поле
            </button>
            <button
              type="button"
              className={`rv-btn ${confirmReady ? "rv-btn--ready" : ""}`}
              disabled={!confirmReady || confirming}
              onClick={() => void confirm()}
            >
              Підтвердити документ
            </button>
          </div>
        </div>

        <div className={`rv-strip ${allResolved ? "rv-strip--done" : ""}`}>
          {allResolved ? (
            <span>Усі поля підтверджено — документ готовий ✓</span>
          ) : (
            <span>
              Потребують уваги: <b>{unresolvedCount}</b> з {flags.length} полів — решту внесено
              автоматично
            </span>
          )}
        </div>
        {confirmError && <p role="alert">{confirmError}</p>}

        <div className="rv-layout">
          <div className="rv-docpane">
            <DocumentPane
              fileUrl={fileUrl}
              filename={doc.filename}
              mode={doc.mode}
              highlight={highlight}
              onHighlightResolved={setHighlightFound}
            />
          </div>
          <div className="rv-fieldspane">
            {reviewState ? (
              <FieldsPane
                extraction={reviewState.extraction}
                flags={flags}
                openPath={openPath}
                pendingPath={reviewState.pendingPath}
                showSnippetDrawer={showSnippetDrawer}
                onToggle={toggleField}
                onSubmitEdit={(path, value) => void submitEdit(path, value)}
                onAcceptAsIs={acceptAsIs}
              />
            ) : (
              <p>Документ ще обробляється — поля з’являться після екстракції.</p>
            )}
          </div>
        </div>
      </div>

      <div className="rv-bar rv-wrap">
        <button type="button" className="rv-btn rv-btn--next" onClick={goToNextField}>
          Наступне поле
        </button>
        <button
          type="button"
          className={`rv-btn rv-btn--confirm ${confirmReady ? "rv-btn--ready" : ""}`}
          disabled={!confirmReady || confirming}
          onClick={() => void confirm()}
        >
          Підтвердити документ
        </button>
      </div>
      <div className={`rv-toast ${toast ? "rv-toast--show" : ""}`}>{toast}</div>
    </div>
  );
}
