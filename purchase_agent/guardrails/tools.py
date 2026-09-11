"""업무 단계별 모델 도구 노출. 서비스의 실제 권한 검사를 대체하지 않는다."""

from langchain.agents.middleware import AgentMiddleware


class WorkflowToolsMiddleware(AgentMiddleware):
    """현재 모델 단계에서 업무 선행 조건이 충족된 도구만 노출한다."""

    def __init__(self, session):
        self.session = session

    def wrap_model_call(self, request, handler):
        # 도구 노출은 모델의 선택을 안내한다. 실제 권한·버전 검사는 service 책임이다.
        allowed = {
            "upsert_purchase_request",
            "save_user_preferences",
            "search_coupang_products",
            "get_department_budget",
        }
        session = self.session
        if not session.department_budget_requested:
            allowed.discard("get_department_budget")
        if (
            not session.current_request
            and session.explored
            and session.draft_inputs.get("quantity")
            and not session.draft_inputs.get("budget_krw")
            and not session.department_budget_requested
        ):
            allowed = set()
        if session.current_request:
            current = session.service.get_latest_request(session.context, session.current_request)
            if current.ok:
                d = current.data
                allowed.add("get_request_status")
                if d.request.selected_evidence_id:
                    allowed.add("review_purchase_request")
                    if d.review:
                        allowed.add("generate_documents")
                    if (
                        d.review
                        and d.review.can_submit
                        and d.documents
                        and d.documents.complete
                        and not session.rejected_this_turn
                        and session.submission_requested
                    ):
                        allowed.add("submit_purchase_request")
        # 검색 완료 후에는 도구를 닫아 선택·문서 생성까지 임의로 진행하지 않게 한다.
        if session.search_only:
            allowed &= {
                "upsert_purchase_request",
                "search_coupang_products",
                "get_request_status",
                "save_user_preferences",
                "get_department_budget",
            }
        if session.search_only and session.search_completed:
            allowed = set()
        if session.document_generated:
            allowed = (
                {"submit_purchase_request"}
                if session.submission_requested and not session.rejected_this_turn
                else set()
            )
        tools = [
            t
            for t in request.tools
            if (getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None))
            in allowed
        ]
        return handler(request.override(tools=tools))
