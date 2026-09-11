"""Explicitly authorized live model evaluation with labeled synthetic shopping data."""

import argparse
import hashlib
import json
import math
import platform
import statistics
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from evaluation_data import synthetic_catalog

from purchase_agent.agent import AgentSession
from purchase_agent.config import demo_context
from purchase_agent.schemas import ListQuery
from purchase_agent.workflow import LocalPurchaseService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["acceptance", "latency"], default="acceptance")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--catalog", choices=["synthetic", "user-confirmed"], default="synthetic")
    args = parser.parse_args()
    if not 1 <= args.runs <= 20:
        raise SystemExit("runs must be 1..20")
    from purchase_agent.catalog import load_catalog

    inputs = (
        load_catalog(ROOT / "fixtures/coupang")
        if args.catalog == "user-confirmed"
        else synthetic_catalog()
    )
    source_hash = hashlib.sha256(
        b"".join(p.read_bytes() for p in sorted((ROOT / "purchase_agent").rglob("*.py")))
    ).hexdigest()
    results = []
    for i in range(args.runs):
        with tempfile.TemporaryDirectory() as directory:
            service = LocalPurchaseService(Path(directory) / "evaluation.db", inputs)
            context = demo_context("employee_a", f"eval{i}")
            session = AgentSession(service, context)
            quantity, budget = [
                (1, 300000),
                (2, 600000),
                (3, 900000),
                (4, 1200000),
                (2, 560000),
                (1, 280000),
                (3, 840000),
                (4, 1120000),
                (1, 500000),
                (2, 900000),
            ][i % 10]
            result = session.invoke(
                f"개발 업무용 모니터 {quantity}대, 배송비 포함 예산 {budget}원, 목적은 신입 개발자 장비 지급이야. 검색어는 모니터로 후보를 찾고 첫 번째 상품을 선택해서 규정 검토와 문서 3종을 작성해줘. 제출은 하지 마. 별도 필수 사양은 없어."
            )
            page = service.list_requests(context, ListQuery()).data
            ready = [
                d
                for d in page.items
                if d.documents
                and d.documents.complete
                and d.review
                and d.review.can_submit
                and d.request.status == "ready"
            ]
            output = result.get("response")
            passed = bool(ready and output and output.status == "documents_ready")
            row = {
                "run": i + 1,
                "passed": passed,
                "status": output.status if output else "pending",
                **result["metrics"],
                "tools": session.budget.tool_results,
            }
            results.append(row)
            print(json.dumps(row), flush=True)
    durations = sorted(r["elapsed_seconds"] for r in results)
    report = {
        "suite": args.suite,
        "data": args.catalog + " catalog; actual model",
        "python": platform.python_version(),
        "source_hash": source_hash,
        "model": session.model.inner.model_name,
        "runs": len(results),
        "passed": sum(r["passed"] for r in results),
        "p50_seconds": statistics.median(durations),
        "p95_seconds": durations[math.ceil(0.95 * len(durations)) - 1],
        "results": results,
    }
    target = ROOT / "runtime" / f"evaluation-{args.suite}-{args.catalog}.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "results"}))
    return (
        0
        if report["passed"] >= math.ceil(0.9 * args.runs)
        and (args.suite != "latency" or report["p95_seconds"] <= 30)
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
