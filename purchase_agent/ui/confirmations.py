"""직접 입력과 AI가 함께 사용하는 최종 확인 창."""

import streamlit as st

from purchase_agent.schemas import DecisionInput
from purchase_agent.ui.execution import execute
from purchase_agent.ui.presentation import ROLES, STATUS, money
from purchase_agent.ui.state import clear_confirmations, conversation


def remember_result(chat, result):
    chat["result"] = result
    if result.get("response"):
        chat.setdefault("history", []).append(("assistant", result["response"].message))


def submission_summary(detail):
    r = detail.request
    selected = next((e for e in detail.candidates if e.evidence_id == r.selected_evidence_id), None)
    if selected:
        st.text(selected.product.productName)
    st.text(f"수량 {r.inputs.quantity}대 · 배송비 포함 {money(detail.review.review_total_krw)}")
    st.text("결재 경로: " + " → ".join(ROLES[a] for a in detail.review.required_approvers))
    st.caption(f"검토한 문서 버전 {r.version} · 실제 주문이나 결제는 진행하지 않습니다.")


@st.dialog("구매요청 제출 확인", dismissible=False, width="medium")
def submission_dialog(service, context, state):
    pending = state["submission"]
    result = service.get_latest_request(context, pending["request_id"])
    detail = result.data if result.ok else None
    valid = bool(
        detail
        and "submit" in detail.allowed_actions
        and detail.documents
        and detail.request.version == pending["version"]
        and detail.documents.bundle_id == pending["bundle_id"]
    )
    if valid:
        submission_summary(detail)
        st.write("위 내용으로 구매팀에 검토를 요청합니다.")
    else:
        st.warning("요청 내용이나 처리 상태가 바뀌었습니다. 최신 문서를 다시 확인해 주세요.")
    a, b = st.columns(2)
    if a.button("취소", key="cancel_submit"):
        if pending["kind"] == "ai":
            chat = conversation(state, pending["request_id"])
            if chat.get("agent") and chat.get("result", {}).get("pending"):
                remember_result(
                    chat, execute(lambda events: chat["agent"].resume(False, on_event=events))
                )
        clear_confirmations(state)
        st.rerun()
    if b.button("제출", key="confirm_submit", type="primary", disabled=not valid):
        if pending["kind"] == "ai":
            chat = conversation(state, pending["request_id"])
            agent = chat.get("agent")
            if agent is None or not chat.get("result", {}).get("pending"):
                st.error("AI 확인 세션이 만료되었습니다. 창을 닫고 다시 제출해 주세요.")
                return
            remember_result(chat, execute(lambda events: agent.resume(True, on_event=events)))
            latest = service.get_latest_request(context, pending["request_id"])
            success = latest.ok and latest.data.request.status == "submitted"
        else:
            success = service.submit_request(context, pending["confirmation"]).ok
        if success:
            clear_confirmations(state)
            state["notice"] = (
                "구매요청을 제출했습니다. 구매팀 검토가 끝나면 처리 상태를 확인할 수 있습니다."
            )
            st.rerun()
        else:
            st.error("제출하지 못했습니다. 취소한 뒤 최신 문서에서 다시 시도해 주세요.")


@st.dialog("결재 처리 확인", dismissible=False, width="medium")
def decision_dialog(service, context, state):
    pending = state["decision"]
    names = {"approve": "승인", "reject": "반려", "request_revision": "보완 요청"}
    result = service.get_latest_request(context, pending["request_id"])
    detail = result.data if result.ok else None
    valid = bool(
        detail
        and detail.request.version == pending["version"]
        and pending["decision"] in detail.allowed_actions
    )
    st.subheader(names[pending["decision"]])
    if valid:
        submission_summary(detail)
        if (
            pending["decision"] == "approve"
            and detail.request.status == "submitted"
            and "manager" in detail.review.required_approvers
        ):
            st.info("100만 원 이상 요청입니다. 구매팀 승인 후 추가 승인자에게 전달됩니다.")
    else:
        st.warning("요청이 변경되었거나 이미 처리되었습니다. 최신 요청을 다시 열어 주세요.")
    reason = st.text_area(
        "처리 의견",
        placeholder="승인 / 보완 / 반려 사유를 입력해주세요",
        key=f"reason_{pending['request_id']}_{pending['version']}_{pending['decision']}",
        max_chars=1000,
    )
    required = pending["decision"] != "approve"
    if required:
        st.caption("보완 요청과 반려에는 처리 의견이 필요합니다.")
    a, b = st.columns(2)
    if a.button("처리 취소"):
        state.pop("decision", None)
        st.rerun()
    if b.button(
        names[pending["decision"]],
        key="confirm_decision",
        type="primary",
        disabled=not valid or (required and not reason.strip()),
    ):
        result = service.decide(context, DecisionInput(**pending, reason=reason.strip() or None))
        if result.ok:
            state.pop("decision", None)
            state["notice"] = STATUS[result.data.status]
            st.rerun()
        else:
            st.error("처리하지 못했습니다. 최신 상태와 권한을 확인해 주세요.")


def show_confirmation(service, context, state):
    if state.get("submission"):
        submission_dialog(service, context, state)
    elif state.get("decision"):
        decision_dialog(service, context, state)
