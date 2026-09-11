"""Load explicitly prepared evidence. Missing catalog stays empty, never synthetic."""

import json
from pathlib import Path

from .schemas import ProductEvidence


def load_catalog(directory="fixtures/coupang"):
    path = Path(directory) / "evidence.json"
    if not path.exists():
        return []
    return [ProductEvidence.model_validate(row) for row in json.loads(path.read_text())]
