"""One actor-scoped Agent session, started only by an explicit user chat event."""

import streamlit as st

from purchase_agent.agent import AgentSession
from purchase_agent.model import model_available


def panel(service, context, state):
    st.subheader("SK-TASK AI 도우미")
    available = model_available()
    if not available:
        st.info("프로젝트 .env에 OpenAI 키를 설정하면 AI 요청을 사용할 수 있습니다.")
        return
    st.caption("실제 AI 모델 · 쇼핑 정보는 모의 API 자료")
    for role, text in state.get("chat_history", [])[-10:]:
        with st.chat_message(role):
            st.text(text)
    # 대화 객체를 재사용해 여러 턴을 이어간다. 새 요청 진입 시 app에서 초기화한다.
    session = state.get("agent")
    pending = state.get("agent_result", {}).get("pending")
    # pending은 제출 완료가 아니라 사용자 결정을 기다리는 Agent 중단 상태다.
    if session and pending:
        st.warning("아래 문서를 확인한 뒤 제출 여부를 선택해 주세요.")
        st.text(f"요청 {pending.request.request_id} · 버전 {pending.request.version}")
        for name, body in pending.documents.files.items():
            with st.expander(name):
                st.text(body)
        st.text(f"배송비 포함 총액: {pending.review.review_total_krw:,}원")
        a, b = st.columns(2)
        decision = None
        if a.button("AI 제출 취소", key="ai_cancel"):
            decision = False
        if b.button("확인 후 제출", key="ai_submit", type="primary"):
            decision = True
        if decision is not None:
            with st.spinner("확인 결과 처리 중…"):
                result = session.resume(decision)
            state["agent_result"] = result
            if result.get("response"):
                state.setdefault("chat_history", []).append(
                    ("assistant", result["response"].message)
                )
            st.rerun()
        return
    with st.form("ai_chat"):
        text = st.text_area(
            "AI 요청", placeholder="신입 3명용 모니터를 배송비 포함 90만 원 안에서 찾아줘"
        )
        consent = st.checkbox("이번 요청의 비교·표현 선호를 기억하는 데 동의합니다.")
        sent = st.form_submit_button("AI에게 요청", type="primary")
    if sent and text.strip():
        from purchase_agent.middleware import redact

        if session is None:
            try:
                session = AgentSession(service, context)
                state["agent"] = session
            except Exception:
                st.error("AI 연결 설정을 확인해 주세요.")
                return
        state.setdefault("chat_history", []).append(("user", redact(text)))
        with st.spinner("구매 조건과 업무 상태를 확인 중…"):
            result = session.invoke(
                text, preference_consent=consent, request_id=state.get("request_id")
            )
        state["agent_result"] = result
        if result.get("response"):
            state["chat_history"].append(("assistant", result["response"].message))
        if session.current_request:
            state["request_id"] = session.current_request
        st.rerun()
    if session and session.current_request:
        if st.button("AI가 작업한 요청 열기"):
            state.update(
                view="detail", request_id=session.current_request, confirmation=None, decision=None
            )
            st.rerun()
