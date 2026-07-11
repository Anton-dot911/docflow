import { useEffect, useState } from "react";
import { exportUrl, fetchDocuments } from "../api/history.ts";
import type { DocumentListItem } from "../api/schemas.ts";
import { ThemeSwitch, type Theme } from "../components/ThemeSwitch.tsx";
import { STATUS_FILTERS, statusQueryParam, type StatusFilter } from "../state/historyFilter.ts";
import { hasInFlightDocuments } from "../state/polling.ts";
import { statusBadge } from "../state/statusBadge.ts";
import { formatMoney } from "../state/format.ts";
import "./review.css";
import "./history.css";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 5000;

function goToReview(documentId: string): void {
  window.location.search = `?id=${documentId}`;
}

export function HistoryPage() {
  const [theme, setTheme] = useState<Theme>(() =>
    window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<DocumentListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // "Завантаження…" only ever covers the very first fetch (the `loading`
  // state's initial value); filter/page changes and polling refreshes swap
  // the list in place once the new page arrives, with no flash back to it.
  useEffect(() => {
    let cancelled = false;
    fetchDocuments({ status: statusQueryParam(filter), limit: PAGE_SIZE, offset })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
        setLoadError(null);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setLoadError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [filter, offset]);

  // Poll every 5s only while something on the current page is still in
  // flight; stops the moment it settles into review/confirmed/failed.
  useEffect(() => {
    if (!hasInFlightDocuments(items.map((item) => item.status))) return;
    let cancelled = false;
    const id = setInterval(() => {
      fetchDocuments({ status: statusQueryParam(filter), limit: PAGE_SIZE, offset })
        .then((response) => {
          if (cancelled) return;
          setItems(response.items);
          setTotal(response.total);
        })
        .catch(() => undefined);
    }, POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [items, filter, offset]);

  function selectFilter(next: StatusFilter) {
    setFilter(next);
    setOffset(0);
  }

  const page = Math.floor(offset / PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="rv-app" data-theme={theme}>
      <div className="rv-wrap hp-wrap">
        <ThemeSwitch theme={theme} onChange={setTheme} />

        <div className="hp-header">
          <span className="rv-logo" aria-hidden="true">
            Df
          </span>
          <div>
            <h1 className="hp-title">Історія документів</h1>
            <div className="rv-header__sub">
              {total} документ{total === 1 ? "" : total >= 2 && total <= 4 ? "и" : "ів"}
            </div>
          </div>
        </div>

        <div className="hp-chips" role="tablist" aria-label="Фільтр за статусом">
          {STATUS_FILTERS.map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={filter === option.value}
              className={`hp-chip ${filter === option.value ? "hp-chip--active" : ""}`}
              onClick={() => selectFilter(option.value)}
            >
              {option.label}
            </button>
          ))}
        </div>

        {loadError && <p role="alert">Не вдалося завантажити список: {loadError}</p>}

        {loading ? (
          <p>Завантаження…</p>
        ) : items.length === 0 ? (
          <p className="hp-empty">Немає документів для цього фільтра.</p>
        ) : (
          <div className="hp-list">
            {items.map((item) => (
              <HistoryRow key={item.id} item={item} onOpen={() => goToReview(item.id)} />
            ))}
          </div>
        )}

        <div className="hp-pager">
          <button
            type="button"
            className="rv-btn rv-btn--ghost"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            ← Попередні
          </button>
          <span className="hp-pager__label">
            сторінка {page} з {pageCount}
          </span>
          <button
            type="button"
            className="rv-btn rv-btn--ghost"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            Наступні →
          </button>
        </div>
      </div>
    </div>
  );
}

interface HistoryRowProps {
  item: DocumentListItem;
  onOpen: () => void;
}

function HistoryRow({ item, onOpen }: HistoryRowProps) {
  const badge = statusBadge(item.status);
  const confirmed = item.status === "confirmed";

  return (
    <div
      className="hp-row"
      role="button"
      tabIndex={0}
      onClick={onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="hp-row__main">
        <span className="hp-row__filename">{item.filename}</span>
        <span className="hp-row__meta">
          {item.doc_type ?? "документ"} · {new Date(item.created_at).toLocaleString("uk-UA")}
        </span>
      </div>

      <span className={`hp-badge hp-badge--${badge.tone}`}>{badge.label}</span>

      <span className="hp-row__total">{item.total !== null ? formatMoney(item.total) : "—"}</span>

      <span className="hp-row__flags">
        {item.flags_count !== null && item.flags_count > 0 ? (
          <span className="hp-flags-count">{item.flags_count} на перевірку</span>
        ) : (
          "—"
        )}
      </span>

      <div className="hp-row__actions">
        {confirmed && (
          <>
            <a
              className="rv-btn rv-btn--ghost hp-download"
              href={exportUrl(item.id, "json")}
              download
              onClick={(event) => event.stopPropagation()}
            >
              JSON
            </a>
            <a
              className="rv-btn rv-btn--ghost hp-download"
              href={exportUrl(item.id, "csv")}
              download
              onClick={(event) => event.stopPropagation()}
            >
              CSV
            </a>
          </>
        )}
      </div>
    </div>
  );
}
