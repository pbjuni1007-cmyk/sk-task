"""승인받은 실제 모델 대화 점검. 별도 DB와 사용자 확인 상품을 사용한다."""

import hashlib
import json
import platform
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from purchase_agent.agent import AgentSession
from purchase_agent.catalog import load_catalog
from purchase_agent.config import demo_context
from purchase_agent.workflow import LocalPurchaseService

rows = []
with tempfile.TemporaryDirectory() as d:
    service = LocalPurchaseService(
        Path(d) / "dialogues.db", load_catalog(ROOT / "fixtures/coupang")
    )
    session = AgentSession(service, demo_context("employee_a", "dialogues"))
    for prompt in [
        "업무용 모니터 3대, 배송비 포함 예산 60만원, 목적은 신입 개발자 장비 지급이야. 모니터 후보를 찾아줘.",
        "클라인즈 상품을 선택하고 문서 3종 만들어줘. 제출은 하지마.",
        "선택 상품과 목적은 그대로 두고 수량만 4대로 바꿔서 검토하고 문서 다시 만들어줘.",
        "제출해줘",
    ]:
        result = session.invoke(prompt)
        if "pending" in result:
            before = service.get_latest_request(
                session.context, session.current_request
            ).data.request.status
            result = session.resume(False)
            after = service.get_latest_request(
                session.context, session.current_request
            ).data.request.status
            assert before == after == "ready"
        response = result.get("response")
        latest = (
            service.get_latest_request(session.context, session.current_request).data
            if session.current_request
            else None
        )
        row = {
            "input": prompt,
            "status": response.status if response else "pending",
            "message": response.message if response else "",
            "metrics": result["metrics"],
            "quantity": latest.request.inputs.quantity if latest else None,
            "total": latest.review.review_total_krw if latest and latest.review else None,
            "documents": bool(latest and latest.documents),
            "tools": session.budget.tool_results,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    for prompt in ["점심 메뉴 추천해줘", "모니터 구매요청서 써줘"]:
        s = AgentSession(service, demo_context("employee_b", "other" + str(len(rows))))
        result = s.invoke(prompt)
        row = {
            "input": prompt,
            "status": result["response"].status,
            "message": result["response"].message,
            "metrics": result["metrics"],
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
assert [row["status"] for row in rows[:3]] == [
    "candidates_ready",
    "documents_ready",
    "documents_ready",
]
assert rows[1]["total"] == 342000 and rows[2]["total"] == 456000
assert rows[4]["metrics"]["tool_attempts"] == 0 and rows[5]["metrics"]["tool_attempts"] == 0
report = {
    "data": "user-confirmed real products; mock shopping API; actual OpenAI model",
    "python": platform.python_version(),
    "source_hash": hashlib.sha256((ROOT / "purchase_agent/agent.py").read_bytes()).hexdigest(),
    "results": rows,
}
(ROOT / "runtime/evaluation-dialogues.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2)
)
