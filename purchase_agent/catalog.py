"""명시적으로 준비된 근거를 불러온다. 카탈로그가 없으면 빈 상태로 두고 가상 데이터를 만들지 않는다."""

import json
from pathlib import Path

from .schemas import ProductEvidence


def load_catalog(directory="fixtures/coupang"):
    path = Path(directory) / "evidence.json"
    if not path.exists():
        return []
    return [ProductEvidence.model_validate(row) for row in json.loads(path.read_text())]
