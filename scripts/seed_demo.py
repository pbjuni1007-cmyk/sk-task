"""새 DB에만 가상 사내 구매 이력을 생성한다. 외부 API는 호출하지 않는다."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from purchase_agent.catalog import load_catalog
from purchase_agent.config import demo_context
from purchase_agent.schemas import DecisionInput, RequestInput, RequestPatch
from purchase_agent.workflow import LocalPurchaseService

# 오래된 완료 건부터 현재 작업 건 순서. 목록은 최근 생성 순으로 표시된다.
SCENARIOS = [
    (
        "employee_a",
        "개발팀 신규 입사자 2명 업무용 모니터 지급",
        8187823028,
        2,
        400000,
        "approved",
        "입사 일정과 지급 수량 확인. 표준 장비로 승인합니다.",
    ),
    (
        "employee_b",
        "운영팀 고객지원 좌석 노후 모니터 교체",
        8691064687,
        3,
        400000,
        "approved",
        "기존 장비 불량 확인. 교체 구매 승인합니다.",
    ),
    (
        "employee_a",
        "개발팀 테스트 랩 공용 모니터 6대 확충",
        7975403014,
        6,
        1500000,
        "approved",
        "공용 테스트 환경 증설 계획 및 비교 견적 확인.",
    ),
    (
        "employee_b",
        "운영팀 회의실 보조 모니터 추가 구매",
        8187823028,
        2,
        400000,
        "rejected",
        "유휴 모니터 2대를 우선 재배치해 주세요. 중복 구매로 반려합니다.",
    ),
    (
        "employee_a",
        "개발팀 프로젝트 투입 인력 보조 모니터 지급",
        8187823028,
        3,
        600000,
        "needs_revision",
        "지급 대상자와 기존 장비 보유 여부를 구매 목적에 추가해 주세요.",
    ),
    (
        "employee_a",
        "개발팀 데이터 분석 담당자 와이드 모니터 교체",
        9570277602,
        3,
        1300000,
        "additional_approval",
        "비교 상품과 예산 확인 완료. 100만원 이상으로 추가 승인을 요청합니다.",
    ),
    (
        "employee_b",
        "운영팀 장애 대응 관제 좌석 모니터 교체",
        8691064687,
        4,
        500000,
        "submitted",
        "",
    ),
    ("employee_a", "개발팀 하반기 신입 개발자 장비 지급", 8187823028, 4, 750000, "submitted", ""),
    ("employee_b", "운영팀 재택근무 대여 장비 2세트 준비", 8691064687, 2, 300000, "ready", ""),
    ("employee_a", "개발팀 사내 교육장 실습 좌석 증설 검토", 8187823028, 5, 900000, "draft", ""),
]


def checked(result):
    if not result.ok:
        raise RuntimeError(result.error_code)
    return result.data


def seed(path, empty=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 기존 DB에는 빈 파일이라도 덮어쓰지 않는다.
    with path.open("xb"):
        pass
    service = LocalPurchaseService(path, load_catalog(ROOT / "fixtures/coupang"))
    summary = []
    for index, (actor, purpose, product_id, quantity, budget, status, reason) in enumerate(
        [] if empty else SCENARIOS
    ):
        owner = demo_context(actor, "company-seed")
        request = checked(
            service.create_request(
                owner,
                RequestInput(quantity=quantity, budget_krw=budget, purpose=purpose),
                f"company-{index}",
            )
        )
        if status != "draft":
            candidates = checked(service.search_products(owner, request, "모니터", limit=10))
            selected = next(e for e in candidates if e.product.productId == product_id)
            request = checked(
                service.update_request(
                    owner,
                    request.request_id,
                    RequestPatch(
                        expected_version=request.version, selected_evidence_id=selected.evidence_id
                    ),
                )
            )
            review = checked(service.review_request(owner, request))
            if not review.can_submit:
                raise RuntimeError(f"시나리오 규정 검토 실패: {purpose}")
            docs = checked(service.generate_documents(owner, request))
            if status != "ready":
                confirmation = checked(service.prepare_submission(owner, request, docs.bundle_id))
                checked(service.submit_request(owner, confirmation))
                if status != "submitted":
                    decision = {"rejected": "reject", "needs_revision": "request_revision"}.get(
                        status, "approve"
                    )
                    result = checked(
                        service.decide(
                            demo_context("buyer_a", "company-seed"),
                            DecisionInput(
                                request_id=request.request_id,
                                version=request.version,
                                decision=decision,
                                reason=reason,
                            ),
                        )
                    )
                    if status == "approved" and result.status == "additional_approval":
                        checked(
                            service.decide(
                                demo_context("manager_a", "company-seed"),
                                DecisionInput(
                                    request_id=request.request_id,
                                    version=request.version,
                                    decision="approve",
                                    reason="부서 장비 확충 계획과 예산을 확인하여 승인합니다.",
                                ),
                            )
                        )
        detail = checked(service.get_latest_request(owner, request.request_id))
        if detail.request.status != status:
            raise RuntimeError(f"시나리오 상태 불일치: {purpose}")
        summary.append((status, purpose))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="새로 만들 DB 경로")
    parser.add_argument("--empty", action="store_true", help="구매 요청 없는 연습용 DB 생성")
    args = parser.parse_args()
    try:
        rows = seed(args.db, args.empty)
    except FileExistsError:
        parser.exit(1, "이미 있는 DB입니다. 새 파일명을 지정해 주세요.\n")
    print(f"생성 완료: {args.db.resolve()} ({len(rows)}건, 가상 회사 데이터)")
    for status, purpose in rows:
        print(f"  {status}: {purpose}")
