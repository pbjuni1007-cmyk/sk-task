"""실제 모델·도구 이벤트를 표시한다. 검증 전 모델 원문은 출력하지 않는다."""

from concurrent.futures import ThreadPoolExecutor
from queue import Empty, Queue

import streamlit as st

LABELS = {
    "upsert_purchase_request": "구매 조건 저장",
    "search_coupang_products": "상품 검색",
    "get_department_budget": "모의 부서 예산 조회",
    "review_purchase_request": "예산·구매 규정 검토",
    "generate_documents": "문서 작성",
    "submit_purchase_request": "구매요청 제출",
    "get_request_status": "최신 요청 조회",
    "save_user_preferences": "비교 선호 저장",
}


def execute(action):
    with st.status("요청을 확인하고 있습니다.", expanded=True) as status:
        phase = st.empty()

        def on_event(event):
            kind = event["kind"]
            if kind == "tool_started":
                label = LABELS.get(event["tool"], "업무 처리")
                status.update(label=f"{label} 중…")
                phase.text(f"{label} 중…")
            elif kind == "tool_finished":
                label = LABELS.get(event["tool"], "업무 처리")
                st.write(f"{label} {'완료' if event['ok'] else '확인 필요'}")
            elif kind == "validation_started":
                phase.text("처리 결과를 저장된 업무 데이터와 대조하고 있습니다.")
            elif kind == "model_retry":
                phase.text("보조 AI 연결로 다시 시도하고 있습니다.")
            elif kind == "model_started":
                phase.text("AI가 다음 작업을 판단하고 있습니다.")

        # LangGraph 도구는 별도 스레드에서 실행된다. UI 갱신은 화면 스레드에서만 한다.
        events = Queue()
        with ThreadPoolExecutor(max_workers=1) as worker:
            future = worker.submit(action, events.put)
            while not future.done() or not events.empty():
                try:
                    event = events.get(timeout=0.1)
                except Empty:
                    continue
                on_event(event)
            result = future.result()
        phase.empty()
        failed = result.get("response") and result["response"].status == "failed"
        status.update(
            label="처리 내용을 확인해 주세요."
            if failed
            else "제출 확인 대기"
            if result.get("pending")
            else "처리 완료",
            state="error" if failed else "complete",
            expanded=bool(failed),
        )
        return result
