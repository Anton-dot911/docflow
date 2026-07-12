"""Preprocessing contract (T3).

`PreprocessedDoc` is the output of `services/preprocess.py` and the input to
classification/extraction (T4+). Contract shape is verbatim from docs/PLAN.md:
`PreprocessedDoc {mode: "text"|"vision", text?: str, images?: list[bytes], pages: int}`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, model_validator

PreprocessMode = Literal["text", "vision"]


class PreprocessedDoc(BaseModel):
    """Result of preprocessing one document.

    - ``text`` mode carries the extracted text layer (`text` set, `images` None).
    - ``vision`` mode carries rasterized/normalized PNG page images (`images`
      non-empty, `text` None).
    `pages` is the number of pages actually processed (capped in T3 — see
    `services/preprocess.py` and docs/decisions.md).

    `first_page_text` (T10) additionally carries just page 1's text in text
    mode, so the classifier can send page 1 only per its task spec without
    re-parsing the source bytes; unset in vision mode, where `images[0]` is
    already page 1 on its own.
    """

    mode: PreprocessMode
    text: str | None = None
    images: list[bytes] | None = None
    pages: int
    first_page_text: str | None = None

    @model_validator(mode="after")
    def _check_mode_invariants(self) -> PreprocessedDoc:
        if self.mode == "text":
            if not self.text:
                raise ValueError("text mode requires non-empty text")
        elif not self.images:
            raise ValueError("vision mode requires at least one image")
        return self
