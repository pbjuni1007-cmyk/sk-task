"""Deterministic policy: no model-provided price, shipping or approval decisions."""

from uuid import uuid4

from .schemas import PolicyCheck, ProductEvidence, ProductSupplement, PurchaseRequest, ReviewResult

POLICY_VERSION = "purchase-v2"


def shipping_total(s: ProductSupplement, quantity: int) -> int | None:
    if (
        s.source_status != "verified"
        or not s.source_checked_at
        or not all((s.item_id, s.vendor_item_id, s.option_label, s.shipping_source_url))
    ):
        return None
    if s.shipping_rule == "free":
        return 0
    if s.shipping_rule == "per_order":
        return s.fee_krw
    if s.shipping_rule == "per_item":
        return None if s.fee_krw is None else s.fee_krw * quantity
    if s.shipping_rule == "tiered":
        matches = [t.fee_krw for t in s.tiers if t.min_quantity <= quantity <= t.max_quantity]
        return matches[0] if len(matches) == 1 else None
    return None


def eligible(e: ProductEvidence, requirements: list[str], quantity: int) -> bool:
    # Hard constraints require explicit catalog evidence, not an LLM inference.
    return shipping_total(e.supplement, quantity) is not None and all(
        r.strip().casefold() in {fact.strip().casefold() for fact in e.supplement.verified_specs}
        for r in requirements
    )


def review(request: PurchaseRequest, candidates: list[ProductEvidence]) -> ReviewResult:
    selected = next((e for e in candidates if e.evidence_id == request.selected_evidence_id), None)
    quantity = request.inputs.quantity
    subtotal = selected.product.productPrice * quantity if selected else 0
    fee = shipping_total(selected.supplement, quantity) if selected else None
    total = subtotal + fee if selected and fee is not None else None
    missing = (
        ([] if request.inputs.purpose else ["purpose"])
        + ([] if selected else ["selected_product"])
        + ([] if fee is not None else ["shipping"])
    )
    valid = {
        e.product.productId
        for e in candidates
        if eligible(e, request.inputs.requirements, quantity)
    }
    checks = [
        PolicyCheck(
            policy_id="POL-01",
            result="pass" if request.inputs.purpose and selected else "fail",
            reason="목적·선택 상품·기본 입력 확인",
        ),
        PolicyCheck(
            policy_id="POL-02",
            result="unknown"
            if total is None
            else ("pass" if total <= request.inputs.budget_krw else "fail"),
            reason="배송비 포함 총액이 예산 이내여야 합니다.",
        ),
        PolicyCheck(
            policy_id="POL-03",
            result="unknown"
            if total is None
            else ("pass" if total < 500000 or len(valid) >= 2 else "fail"),
            reason=f"비교 가능한 서로 다른 상품 {len(valid)}개; 50만 원 이상은 2개 필요",
        ),
        PolicyCheck(
            policy_id="POL-04", result="pass", reason="100만 원 이상은 구매 담당자 후 추가 승인"
        ),
        PolicyCheck(
            policy_id="POL-05",
            result="pass" if fee is not None else "unknown",
            reason="수량·옵션·판매자에 적용되는 배송 조건 확인",
        ),
        PolicyCheck(policy_id="POL-06", result="pass", reason=f"버전 {request.version} 기준 검토"),
        PolicyCheck(
            policy_id="SPEC",
            result="pass"
            if selected and eligible(selected, request.inputs.requirements, quantity)
            else "unknown",
            reason="필수 사양·상품 근거 확인",
        ),
    ]
    return ReviewResult(
        request_id=request.request_id,
        version=request.version,
        review_id=uuid4().hex,
        policy_version=POLICY_VERSION,
        subtotal_krw=subtotal,
        shipping_fee_krw=fee,
        review_total_krw=total,
        remaining_krw=None if total is None else request.inputs.budget_krw - total,
        checks=checks,
        required_approvers=["buyer", "manager"]
        if total is not None and total >= 1000000
        else ["buyer"],
        can_submit=all(c.result == "pass" for c in checks),
        missing_fields=missing,
    )
