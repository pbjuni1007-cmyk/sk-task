"""화면 표현. 사용자·상품 문자열은 HTML/Markdown으로 실행하지 않는다."""

from html import escape
from pathlib import Path

import streamlit as st

STATUS = {
    "draft": "작성 중",
    "ready": "제출 준비 완료",
    "submitted": "구매팀 검토 중",
    "additional_approval": "추가 승인 대기",
    "approved": "승인 완료",
    "rejected": "반려",
    "needs_revision": "보완 요청",
}
ROLES = {"requester": "요청 직원", "buyer": "구매 담당자", "manager": "추가 승인자"}
PROFILES = {
    "employee_a": "박직원 · 개발팀",
    "employee_b": "김직원 · 운영팀",
    "buyer_a": "이담당 · 구매팀",
    "manager_a": "최승인 · 경영지원팀",
}
DOCS = {"purchase_request": "구매요청서", "comparison": "상품 비교표", "review": "규정 검토"}


def money(value):
    return "확인 필요" if value is None else f"{value:,}원"


def style():
    st.markdown(
        f"<style>{Path(__file__).with_name('style.css').read_text()}</style>",
        unsafe_allow_html=True,
    )


def badge(status):
    st.markdown(
        f'<span class="status status-{escape(status)}">{escape(STATUS[status])}</span>',
        unsafe_allow_html=True,
    )


def heading(title, subtitle=""):
    st.markdown(f'<div class="page-title">{escape(title)}</div>', unsafe_allow_html=True)
    if subtitle:
        st.text(subtitle)


def steps(current):
    labels = ["구매 조건", "상품 선택", "검토 및 제출"]
    items = "".join(
        f'<span class="step {"active" if i == current else ""}"><b>{i}</b> {label}</span>'
        for i, label in enumerate(labels, 1)
    )
    st.markdown(f'<div class="steps">{items}</div>', unsafe_allow_html=True)


def progress(detail):
    status = detail.request.status
    labels = ["요청 작성", "구매팀 검토"]
    if detail.review and "manager" in detail.review.required_approvers:
        labels.append("추가 승인")
    labels.append("승인 완료")
    active = {
        "draft": 0,
        "ready": 0,
        "submitted": 1,
        "additional_approval": 2,
        "approved": len(labels) - 1,
    }.get(status)
    text = " → ".join(
        f"<strong>{label}</strong>" if i == active else label for i, label in enumerate(labels)
    )
    st.markdown(f'<div class="progress-line">{text}</div>', unsafe_allow_html=True)
    if status == "needs_revision":
        st.warning(
            "구매팀이 보완을 요청했습니다. 아래 처리 의견을 확인하고 구매 내용을 수정해 주세요."
        )
    elif status == "rejected":
        st.warning("반려된 요청입니다. 처리 의견을 확인한 뒤 새 버전으로 수정할 수 있습니다.")


def document_preview(detail, kind):
    """저장 문서의 구조를 화면으로 표현한다. 사용자 입력은 st.text로 출력한다."""
    r, review = detail.request, detail.review
    selected = next((e for e in detail.candidates if e.evidence_id == r.selected_evidence_id), None)
    with st.container(border=True, key=f"paper_{kind}"):
        st.subheader(DOCS[kind])
        st.caption(f"요청 {r.request_id[:8]} · 버전 {r.version}")
        if selected:
            st.text(selected.product.productName)
            st.caption(f"수량 {r.inputs.quantity}대 · 단가 {money(selected.product.productPrice)}")
        if review:
            st.text(
                f"상품금액 {money(review.subtotal_krw)}  +  배송비 {money(review.shipping_fee_krw)}"
            )
            st.markdown(f"**총액 {money(review.review_total_krw)}**")
        st.divider()
        if kind == "purchase_request":
            st.markdown("**구매 목적**")
            st.text(r.inputs.purpose or "제출 전 입력 필요")
            st.markdown("**희망 사양**")
            st.text(" · ".join(r.inputs.requirements) or "별도 지정 없음")
            st.text(f"예산 {money(r.inputs.budget_krw)}")
        elif kind == "comparison":
            st.dataframe(
                [
                    {
                        "상품": e.product.productName,
                        "단가": money(e.product.productPrice),
                        "선택": "선택 상품"
                        if selected and e.evidence_id == selected.evidence_id
                        else "",
                    }
                    for e in detail.candidates
                ],
                hide_index=True,
                width="stretch",
            )
        elif review:
            for check in review.checks:
                st.text(f"{'✓' if check.result == 'pass' else '보완 필요 ·'} {check.reason}")
        st.caption("모의 상품 자료 기준 · 실제 주문·결제 문서가 아닙니다.")
