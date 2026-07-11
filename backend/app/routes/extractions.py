"""HTTP layer for the T7 Review UI's single-field edit endpoint.

Thin: resolve the extraction row, apply the edit via `app.services.field_path`,
revalidate the whole payload against `InvoiceData` (money/date coercion +
schema safety), persist, and write a `review_log` row. Repos are provided via
FastAPI dependencies so unit tests can override them with fakes.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from app.models.domain import FieldConfidence, InvoiceData
from app.models.review import ExtractionDetail, PatchExtractionRequest
from app.repos.extractions import ExtractionsRepo
from app.repos.review_log import ReviewLogRepo
from app.services.field_path import FieldPathError, get_field_value, set_field_value

router = APIRouter(prefix="/api/extractions", tags=["extractions"])


def get_extractions_repo() -> ExtractionsRepo:
    return ExtractionsRepo()


def get_review_log_repo() -> ReviewLogRepo:
    return ReviewLogRepo()


@router.patch("/{extraction_id}", response_model=ExtractionDetail)
def patch_extraction(
    extraction_id: UUID,
    body: PatchExtractionRequest,
    extractions: Annotated[ExtractionsRepo, Depends(get_extractions_repo)],
    review_log: Annotated[ReviewLogRepo, Depends(get_review_log_repo)],
) -> ExtractionDetail:
    """Apply one field edit: update payload, set confidence to 1.0, log it.

    Accepting a flagged field as-is ("Прийняти як є") is the same request with
    `new_value` equal to the current value — the confidence bump and
    review_log write are identical either way. Any T6 validation issue at
    `field_path` is cleared: the operator has now looked at it, so the field
    should render green (not red) on the next GET, per UI_SPEC.
    """
    row = extractions.get_by_id(extraction_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="extraction not found")

    payload = row["payload"]
    try:
        old_value = get_field_value(payload, body.field_path)
        new_payload = set_field_value(payload, body.field_path, body.new_value)
        validated_payload = InvoiceData.model_validate(new_payload)
    except (FieldPathError, ValidationError) as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"invalid field_path or value: {error}",
        ) from error

    confidences = [FieldConfidence.model_validate(c) for c in row["field_confidences"]]
    if any(c.path == body.field_path for c in confidences):
        updated_confidences = [
            c.model_copy(update={"confidence": 1.0}) if c.path == body.field_path else c
            for c in confidences
        ]
    else:
        updated_confidences = [
            *confidences,
            FieldConfidence(path=body.field_path, confidence=1.0, source_snippet=None),
        ]

    remaining_issues = [i for i in row["validation_issues"] if i["path"] != body.field_path]

    updated_row = extractions.update_after_edit(
        extraction_id,
        payload=validated_payload.model_dump(mode="json"),
        field_confidences=[c.model_dump(mode="json") for c in updated_confidences],
        validation_issues=remaining_issues,
    )
    review_log.create(
        extraction_id=extraction_id,
        field_path=body.field_path,
        old_value=old_value,
        new_value=body.new_value,
    )
    return ExtractionDetail.model_validate(updated_row)
