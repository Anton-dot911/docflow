import { useEffect, useRef, useState } from "react";
import * as pdfjsLib from "pdfjs-dist";
import { TextLayer } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import { findSnippetItemIndices } from "../state/textSearch.ts";
import type { FlagSeverity } from "../state/flags.ts";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

// T3 preprocessing caps at 20 pages; the Review UI document pane mirrors that
// cap for the original file too (UI_SPEC §5: out of scope for T7 to
// virtualize beyond it).
const MAX_PAGES = 20;
const RENDER_SCALE = 1.4;

export interface HighlightRequest {
  snippet: string;
  severity: FlagSeverity;
}

interface RenderedPage {
  textDivs: HTMLElement[];
  textItems: string[];
}

interface DocumentPaneProps {
  fileUrl: string | null;
  filename: string;
  mode: "text" | "vision" | null;
  highlight: HighlightRequest | null;
  onHighlightResolved?: (found: boolean) => void;
}

function isImageFile(filename: string): boolean {
  return /\.(jpe?g|png)$/i.test(filename);
}

// Source chip text: we don't carry per-document provenance (e.g. "via
// Viber"), only T3's text/vision mode — so the chip communicates that
// distinction instead (see docs/decisions.md).
function sourceLabel(mode: "text" | "vision" | null, isImage: boolean): string {
  if (isImage || mode === "vision") return "Скан / Фото";
  return "PDF";
}

export function DocumentPane({
  fileUrl,
  filename,
  mode,
  highlight,
  onHighlightResolved,
}: DocumentPaneProps) {
  const bodyRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<RenderedPage[]>([]);
  const marksRef = useRef<HTMLElement[]>([]);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [renderedPageCount, setRenderedPageCount] = useState(0);

  const image = isImageFile(filename);

  useEffect(() => {
    if (!fileUrl || image) return undefined;
    const container = bodyRef.current;
    if (!container) return undefined;

    let cancelled = false;
    container.innerHTML = "";
    pagesRef.current = [];
    setRenderError(null);
    setRenderedPageCount(0);

    async function renderDocument(url: string, containerEl: HTMLDivElement) {
      try {
        const pdf = await pdfjsLib.getDocument({ url }).promise;
        const pageCount = Math.min(pdf.numPages, MAX_PAGES);
        // Render at a scale that fills the pane's actual width, so pdf.js's
        // absolutely-positioned text-layer spans line up with the canvas
        // pixel-for-pixel (no CSS-side rescaling to fight against).
        const containerWidth = containerEl.clientWidth;
        for (let pageNumber = 1; pageNumber <= pageCount; pageNumber += 1) {
          if (cancelled) return;
          const page = await pdf.getPage(pageNumber);
          const baseViewport = page.getViewport({ scale: 1 });
          const scale = containerWidth > 0 ? containerWidth / baseViewport.width : RENDER_SCALE;
          const viewport = page.getViewport({ scale });

          const pageDiv = document.createElement("div");
          pageDiv.className = "rv-pdf-page";
          pageDiv.style.width = `${viewport.width}px`;
          pageDiv.style.height = `${viewport.height}px`;

          const canvas = document.createElement("canvas");
          canvas.width = viewport.width;
          canvas.height = viewport.height;
          const ctx = canvas.getContext("2d");
          pageDiv.appendChild(canvas);

          const textLayerDiv = document.createElement("div");
          textLayerDiv.className = "rv-pdf-textlayer";
          textLayerDiv.style.width = `${viewport.width}px`;
          textLayerDiv.style.height = `${viewport.height}px`;
          pageDiv.appendChild(textLayerDiv);

          containerEl.appendChild(pageDiv);

          if (ctx) {
            await page.render({ canvas, canvasContext: ctx, viewport }).promise;
          }
          const textContent = await page.getTextContent();
          const textLayer = new TextLayer({
            textContentSource: textContent,
            container: textLayerDiv,
            viewport,
          });
          await textLayer.render();
          if (cancelled) return;
          pagesRef.current.push({
            textDivs: textLayer.textDivs,
            textItems: textLayer.textContentItemsStr,
          });
        }
        if (!cancelled) setRenderedPageCount(pageCount);
      } catch (cause) {
        if (!cancelled) {
          setRenderError(cause instanceof Error ? cause.message : String(cause));
        }
      }
    }

    void renderDocument(fileUrl, container);
    return () => {
      cancelled = true;
    };
  }, [fileUrl, image]);

  useEffect(() => {
    for (const mark of marksRef.current) {
      mark.classList.remove("rv-mark--warn", "rv-mark--err");
    }
    marksRef.current = [];

    if (!highlight || image) {
      onHighlightResolved?.(false);
      return;
    }

    for (const page of pagesRef.current) {
      const indices = findSnippetItemIndices(page.textItems, highlight.snippet);
      if (indices) {
        const markClass = highlight.severity === "err" ? "rv-mark--err" : "rv-mark--warn";
        const divs = indices
          .map((i) => page.textDivs[i])
          .filter((div): div is HTMLElement => !!div);
        divs.forEach((div) => div.classList.add(markClass));
        marksRef.current = divs;
        divs[0]?.scrollIntoView({ behavior: "smooth", block: "center" });
        onHighlightResolved?.(true);
        return;
      }
    }
    onHighlightResolved?.(false);
    // renderedPageCount is a dependency proxy for "the text layers just changed".
  }, [highlight, renderedPageCount, image, onHighlightResolved]);

  return (
    <div className="rv-scanframe">
      <span className="rv-scanframe__pill">СКАН / ФОТО</span>
      <div className="rv-paper">
        <div className="rv-paper__head">
          <div>
            <span className="rv-paper__kicker">Оригінал документа</span>
            <h2 className="rv-paper__title">{filename}</h2>
          </div>
          <span className="rv-paper__source">{sourceLabel(mode, image)}</span>
        </div>
        <div className="rv-paper__body" ref={bodyRef}>
          {!fileUrl && <p>Завантаження документа…</p>}
          {image && fileUrl && <img src={fileUrl} alt={filename} />}
          {renderError && <p role="alert">Не вдалося відобразити документ: {renderError}</p>}
        </div>
      </div>
    </div>
  );
}
