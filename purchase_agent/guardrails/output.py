"""모델의 상품·금액·완료 주장을 DB 근거와 대조한다."""

from .input import redact


def validate_response(session, output):
    # 모델의 완료 주장을 신뢰하지 않고 요청·버전·문서 ID를 DB와 대조한다.
    if output.request_id is None:
        if any(
            (
                output.version is not None,
                output.review_id,
                output.document_bundle_id,
                output.submitted_at,
                output.status in ("submitted", "documents_ready"),
            )
        ):
            raise ValueError("UNGROUNDED_OUTPUT")
        ids = {e.product.productId for e in session.explored}
        if not set(output.candidate_ids) <= ids or (
            output.status == "candidates_ready" and not ids
        ):
            raise ValueError("UNGROUNDED_OUTPUT")
        missing = [k for k in ("quantity", "budget_krw") if not session.draft_inputs.get(k)]
        labels = {"quantity": "수량", "budget_krw": "이번 구매의 배송비 포함 예산"}
        known = (
            f"모니터 {session.draft_inputs['quantity']}대 구매로 이해했습니다. "
            if session.draft_inputs.get("quantity")
            else ""
        )
        found = (
            "등록된 모의 상품 후보를 찾았습니다. 아래에서 가격을 비교할 수 있습니다. "
            if session.explored
            else "예산을 정하기 전에도 상품을 먼저 검색할 수 있습니다. "
        )
        output.message = (
            known
            + found
            + (
                "요청서를 만들려면 "
                + "와 ".join(labels[k] for k in missing)
                + "을 알려주세요. 팀 예산을 적용하도록 요청해도 됩니다."
                if missing
                else "구매 조건을 확인해 주세요."
            )
        )
        if output.status == "blocked":
            output.message = "[before 가드레일 발동] 현재 요청을 처리하지 못했습니다. 개발팀 담당자(김기현 - 내선 5314)에게 문의해주세요."
        output.missing_fields = missing
        output.candidate_ids = [e.product.productId for e in session.explored]
    else:
        value = session.service.get_latest_request(session.context, output.request_id)
        if not value.ok:
            raise ValueError("UNGROUNDED_OUTPUT")
        d = value.data
        if output.version != d.request.version:
            raise ValueError("STALE_OUTPUT")
        if not set(output.candidate_ids) <= {e.product.productId for e in d.candidates}:
            raise ValueError("UNKNOWN_PRODUCT")
        if output.review_id and (not d.review or output.review_id != d.review.review_id):
            raise ValueError("UNGROUNDED_REVIEW")
        if output.document_bundle_id and (
            not d.documents or output.document_bundle_id != d.documents.bundle_id
        ):
            raise ValueError("UNGROUNDED_DOCUMENT")
        if output.status == "documents_ready" and (
            not d.documents
            or not d.documents.complete
            or output.document_bundle_id != d.documents.bundle_id
        ):
            raise ValueError("FALSE_DOCUMENT_COMPLETION")
        if output.status == "candidates_ready" and not d.candidates:
            raise ValueError("FALSE_CANDIDATES")
        if output.status == "submitted" and (
            d.request.status != "submitted" or output.submitted_at != d.request.submitted_at
        ):
            raise ValueError("FALSE_SUBMISSION")
        # 수치 정보는 검증되지 않은 문장 대신 서버가 제어하는 UI에 표시한다.
        if output.status in ("documents_ready", "submitted", "candidates_ready"):
            output.message = {
                "documents_ready": "문서 초안을 작성했습니다. 상세 화면에서 금액과 보완 사항을 확인하세요.",
                "submitted": "구매요청을 제출했습니다.",
                "candidates_ready": "저장된 상품 후보를 확인해 주세요.",
            }[output.status]
        if output.status in ("needs_revision", "needs_input"):
            output.message = (
                (
                    "보완 사항: "
                    + " / ".join(c.reason for c in d.review.checks if c.result != "pass")
                )
                if d.review and not d.review.can_submit
                else "구매 조건을 저장했습니다. 상세 화면에서 후보·선택 상품·문서를 확인해 주세요."
            )
            output.missing_fields = (
                d.review.missing_fields
                if d.review
                else ([] if d.request.selected_evidence_id else ["selected_product"])
            )
        if output.status in ("blocked", "failed"):
            output.message = "[before 가드레일 발동] 현재 요청을 처리하지 못했습니다. 개발팀 담당자(김기현 - 내선 5314)에게 문의해주세요."
        preferences = session.service.get_preferences(session.context)
        if preferences.ok and preferences.data.get("output_style") == "detailed":
            total = (
                f"{d.review.review_total_krw:,}원"
                if d.review and d.review.review_total_krw is not None
                else "확인 필요"
            )
            output.message += f"\n수량: {d.request.inputs.quantity}대 · 예산: {d.request.inputs.budget_krw:,}원 · 배송비 포함 총액: {total}"
        from ..preferences import order_candidates

        ordered = order_candidates(
            d.candidates, preferences.data if preferences.ok else {}, d.request.inputs
        )
        selected_ids = set(output.candidate_ids)
        output.candidate_ids = [
            e.product.productId for e in ordered if e.product.productId in selected_ids
        ]
        session.current_request = output.request_id
    if session.rejected_this_turn:
        output.message = "제출을 취소했습니다. 문서는 보관되며 제출되지 않았습니다."
    output.message = redact(output.message)
    output.warnings = ["쇼핑 API 모의 데이터"]
    return output
