"""Export JSON Schemas for non-Python consumers (Console, agents' structured output).

Usage: ``uv run python -m subpoena_schemas.export_json packages/schemas/json``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

from . import (
    EvaluationRequest,
    EvaluationResponse,
    EvidenceFinding,
    PipelineEvent,
    Policy,
    Subpoena,
    Testimony,
    TestimonyClaims,
    Transaction,
)

EXPORTED: list[type[BaseModel]] = [
    EvaluationRequest,
    EvaluationResponse,
    EvidenceFinding,
    PipelineEvent,
    Policy,
    Subpoena,
    Testimony,
    TestimonyClaims,
    Transaction,
]


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for model in EXPORTED:
        path = out / f"{model.__name__}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "packages/schemas/json")
