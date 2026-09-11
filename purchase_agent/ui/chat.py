"""현재 구매요청에 연결된 AI 대화. 화면 이동과 요청 생성을 구분한다."""

import streamlit as st

from purchase_agent.agent import AgentSession
from purchase_agent.model import model_available
from purchase_agent.ui.confirmations import remember_result
from purchase_agent.ui.execution import execute
from purchase_agent.ui.state import conversation, reset_execution, sync_version


def panel(service, context, state, detail=None):
    request_id = detail.request.request_id if detail else None
    chat = conversation(state, request_id)
    if detail:
        sync_version(chat, detail.request.version)
    with st.container(key="ai_panel"):
        st.subheader("SK-TASK AI 도우미")
        st.caption("현재 요청의 조건을 정리하고 상품 비교와 문서 작성을 도와드립니다.")
        session = chat.get("agent")
        if session and getattr(session, "department_budget", None):
            budget = session.department_budget
            st.info(
                f"실습용 {budget['department_name']} 예산 · 잔액 {budget['remaining_krw']:,}원 · 건별 한도 {budget['per_request_limit_krw']:,}원"
            )
            st.caption("고정된 모의 예산이며 실제 회계 잔액·지출 예약과 연결되지 않습니다.")
        for role, text in chat.get("history", [])[-10:]:
            with st.chat_message(role):
                st.text(text)
        if not model_available():
            st.info("AI 연결이 설정되지 않았습니다. 왼쪽 양식으로 요청을 진행할 수 있습니다.")
            return
        if chat.get("result", {}).get("pending"):
            st.info("제출 확인 창에서 최종 내용을 확인해 주세요.")
            return
        with st.form(f"ai_chat_{request_id or state['create_id']}", clear_on_submit=True):
            text = st.text_area(
                "AI 요청",
                placeholder="예: 신규 입사자 3명용 모니터를 배송비 포함 50만 원 안에서 찾아줘",
            )
            consent = st.checkbox(
                "상품 비교 선호 기억하기",
                help="동의한 요청에서 비교 순서와 표현 선호만 저장합니다.",
            )
            sent = st.form_submit_button("AI에게 요청", type="primary")
        if not sent or not text.strip():
            return
        from purchase_agent.guardrails.input import redact

        session = chat.get("agent")
        if session is None:
            try:
                session = AgentSession(service, context)
                chat["agent"] = session
            except Exception:
                st.error("AI 연결 설정을 확인해 주세요.")
                return
        chat.setdefault("history", []).append(("user", redact(text)))
        with st.chat_message("user"):
            st.text(redact(text))
        result = execute(
            lambda events: session.invoke(
                text, preference_consent=consent, request_id=request_id, on_event=events
            )
        )
        remember_result(chat, result)
        if session.current_request:
            latest = service.get_latest_request(context, session.current_request)
            if latest.ok:
                current = latest.data
                if request_id != session.current_request:
                    if request_id is not None:
                        previous = chat
                        chat = {**chat, "history": list(chat.get("history", []))}
                        reset_execution(previous)
                    state.setdefault("conversations", {})[session.current_request] = chat
                    state.pop("draft_chat", None)
                state.update(view="detail", request_id=session.current_request)
                if (
                    detail is None
                    or detail.request.version != current.request.version
                    or bool(detail.documents) != bool(current.documents)
                ):
                    state["phase"] = 3 if current.documents else 2
                if detail and detail.request.inputs != current.request.inputs:
                    labels = {
                        "quantity": "수량",
                        "budget_krw": "예산",
                        "purpose": "구매 목적",
                        "requirements": "희망 사양",
                    }
                    changed = [
                        label
                        for field, label in labels.items()
                        if getattr(detail.request.inputs, field)
                        != getattr(current.request.inputs, field)
                    ]
                    state["notice"] = (
                        "AI가 "
                        + ", ".join(changed)
                        + " 항목을 변경했습니다. 최신 내용을 확인해 주세요."
                    )
                chat["version"] = current.request.version
                state.pop("submission", None)
                if result.get("pending"):
                    pending = result["pending"]
                    state["phase"] = 3
                    state["submission"] = dict(
                        kind="ai",
                        request_id=pending.request.request_id,
                        version=pending.request.version,
                        bundle_id=pending.documents.bundle_id,
                    )
        st.rerun()
