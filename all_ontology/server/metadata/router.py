# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""API routes for grading entity coverage of a free-text question."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from all_ontology.retrieval.entity_coverage.state import DEFAULT_MAX_DISTANCE
from all_ontology.server.metadata import service as dal
from all_ontology.server.access import current_zone_ids
from all_ontology.dal.users import resolve_accessible_catalog_ids
from all_ontology.server.responses import EntityCoverageResponse

router = APIRouter()


class EntityCoverageRequest(BaseModel):
    """Payload for the entity-coverage route."""

    question: str = Field(..., min_length=1)
    max_distance: float = Field(
        default=DEFAULT_MAX_DISTANCE,
        gt=0.0,
        description=(
            "Maximum L2 vector distance for a candidate to count "
            "(lower score = closer match)."
        ),
    )


@router.post("/question-entity-coverage", response_model=EntityCoverageResponse)
def entity_coverage(body: EntityCoverageRequest) -> dict:
    """Return ranked semantic candidates and a 0–1 entity coverage grade.

    Extracts entities from the question, retrieves semantic candidates, filters
    by vector distance, enriches from the catalog, and grades how many entities have
    at least one covering ColumnAttribute candidate.

    Returns 422 when the flow cannot produce a result for the question.
    """
    try:
        zone_ids = current_zone_ids()
        result = dal.entity_coverage(
            body.question,
            max_distance=body.max_distance,
            allowed_table_ids=(
                None
                if zone_ids is None
                else sorted(resolve_accessible_catalog_ids(zone_ids)["table_ids"])
            ),
        )
    except dal.PredictionFlowError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": result}
