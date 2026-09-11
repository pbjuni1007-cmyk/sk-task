"""승인받은 소규모 실제 모델 호출 1회. 민감하지 않은 메타데이터만 출력한다."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from purchase_agent.model import make_model

try:
    model = make_model()
    response = model.invoke("Reply with exactly OK.")
    print(
        {
            "model": model.model_name,
            "reply_ok": response.content.strip() == "OK",
            "usage": response.usage_metadata,
        }
    )
except Exception as error:
    print({"error_type": type(error).__name__, "status": getattr(error, "status_code", None)})
    sys.exit(1)
