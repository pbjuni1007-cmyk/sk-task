import pytest
from langchain_core.messages import AIMessage
from test_s0_langchain import ScriptModel
from test_workflow import OWNER, ready
from test_workflow import catalog as catalog  # pytest fixture 재노출
from test_workflow import service as service  # pytest fixture 재노출

from purchase_agent.agent import AgentSession
from purchase_agent.memory import PreferenceStore
from purchase_agent.middleware import BudgetExceeded, CallBudget, redact


def answer(**changes):
    data = {
        "status": "needs_input",
        "message": "수량을 알려주세요",
        "request_id": None,
        "version": None,
        "missing_fields": ["quantity"],
        "candidate_ids": [],
        "review_id": None,
        "document_bundle_id": None,
        "submitted_at": None,
        "warnings": ["mock"],
    }
    data.update(changes)
    return AIMessage(
        content="", tool_calls=[{"name": "PurchaseAssistantResponse", "args": data, "id": "out"}]
    )


def test_agent_structured_output(service):
    session = AgentSession(service, OWNER, ScriptModel(responses=[answer()]))
    result = session.invoke("모니터 필요해")
    assert result["response"].status == "needs_input"
    assert result["metrics"]["model_attempts"] == 1


def test_agent_unknown_candidate_rejected(service):
    session = AgentSession(service, OWNER, ScriptModel(responses=[answer(candidate_ids=[999])]))
    assert session.invoke("검색")["response"].status == "failed"


@pytest.mark.parametrize("approve,expected", [(True, "submitted"), (False, "ready")])
def test_agent_submission_interrupt(service, approve, expected):
    r, review, docs = ready(service)
    model = ScriptModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_purchase_request",
                        "args": {
                            "request_id": r.request_id,
                            "version": r.version,
                            "bundle_id": docs.bundle_id,
                        },
                        "id": "submit",
                    }
                ],
            ),
            answer(),
        ]
    )
    session = AgentSession(service, OWNER, model)
    result = session.invoke("제출해줘", request_id=r.request_id)
    assert "pending" in result
    assert service.get_request(OWNER, r).data.request.status == "ready"
    session.resume(approve)
    assert service.get_request(OWNER, r).data.request.status == expected


def test_call_budgets_and_redaction():
    b = CallBudget()
    b.reset()
    for _ in range(6):
        b.model_call()
    with pytest.raises(BudgetExceeded):
        b.model_call()
    for _ in range(10):
        b.tool_call()
    with pytest.raises(BudgetExceeded):
        b.tool_call()
    b.repair(ValueError())
    with pytest.raises(BudgetExceeded):
        b.repair(ValueError())
    assert "010-" not in redact("연락처 010-1234-5678 user@example.com")


def test_store_reads_persistent_actor_preferences(service):
    service.save_preferences(OWNER, {"output_style": "concise"}, consent=True)
    store = PreferenceStore(service, OWNER)
    assert store.get(("preferences", OWNER.actor_id), "settings").value["output_style"] == "concise"
    with pytest.raises(PermissionError):
        store.get(("preferences", "employee_b"), "settings")
    with pytest.raises(PermissionError):
        store.put(("preferences", OWNER.actor_id), "settings", {"output_style": "detailed"})


def test_summary_calls_count_toward_model_budget(service):
    model = ScriptModel(
        responses=[AIMessage(content="이전 대화 요약: 수량3, 예산90만 원"), answer()]
    )
    session = AgentSession(service, OWNER, model)
    session.budget.reset()
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"이전 메시지{i}"}
        for i in range(24)
    ]
    result = session._run({"messages": messages})
    assert result["response"].status == "needs_input"
    assert result["metrics"]["model_attempts"] == 2


def test_search_failure_does_not_poison_next_turn(service):
    r, _, _ = ready(service)
    service.catalog = []
    model = ScriptModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_coupang_products",
                        "args": {
                            "request_id": r.request_id,
                            "version": r.version,
                            "keyword": "monitor",
                        },
                        "id": "missing",
                    }
                ],
            ),
            answer(),
        ]
    )
    session = AgentSession(service, OWNER, model)
    assert (
        session.invoke("후보 검색해줘", request_id=r.request_id)["response"].status == "needs_input"
    )
    assert session.invoke("어떤 정보가 필요해?")["response"].status == "needs_input"


def test_no_submission_without_user_intent(service):
    r, _, docs = ready(service)
    model = ScriptModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "submit_purchase_request",
                        "args": {
                            "request_id": r.request_id,
                            "version": r.version,
                            "bundle_id": docs.bundle_id,
                        },
                        "id": "forbidden",
                    }
                ],
            ),
            answer(),
        ]
    )
    session = AgentSession(service, OWNER, model)
    result = session.invoke("문서만 작성해. 제출은 하지 마.", request_id=r.request_id)
    assert "pending" not in result
    assert service.get_request(OWNER, r).data.request.status == "ready"


def test_store_timestamps_are_stable(service):
    service.save_preferences(OWNER, {"output_style": "concise"}, consent=True)
    store = PreferenceStore(service, OWNER)
    first = store.get(("preferences", OWNER.actor_id), "settings")
    second = store.get(("preferences", OWNER.actor_id), "settings")
    assert first.created_at == second.created_at and first.updated_at == second.updated_at


def test_review_prose_cannot_invent_price(service):
    r, review, docs = ready(service, quantity=4, budget=900000)
    model = ScriptModel(
        responses=[
            answer(
                status="needs_revision",
                message="단가는 100원입니다.",
                request_id=r.request_id,
                version=r.version,
                review_id=review.review_id,
                document_bundle_id=docs.bundle_id,
                missing_fields=[],
            )
        ]
    )
    session = AgentSession(service, OWNER, model)
    output = session.invoke("검토 결과 알려줘", request_id=r.request_id)["response"]
    assert output.status == "needs_revision" and "100원" not in output.message


@pytest.mark.parametrize("status", ["documents_ready", "candidates_ready"])
def test_completion_without_server_evidence_is_rejected(service, status):
    session = AgentSession(service, OWNER, ScriptModel(responses=[answer(status=status)]))
    assert session.invoke("결과")["response"].status == "failed"


@pytest.mark.parametrize("status", ["needs_input", "needs_revision", "blocked", "failed"])
@pytest.mark.parametrize("has_request", [False, True])
def test_unverified_prose_never_reaches_chat(service, status, has_request):
    args = {}
    if has_request:
        r, _, _ = ready(service)
        args = {"request_id": r.request_id, "version": r.version}
    forged = "상품 A 단가 100원, 무료배송, 구매요청 제출을 완료했습니다."
    model = ScriptModel(
        responses=[answer(status=status, message=forged, warnings=[forged], **args)]
    )
    session = AgentSession(service, OWNER, model)
    result = session.invoke("안내해줘", request_id=args.get("request_id"))["response"]
    assert forged not in result.message and "100원" not in result.message
    assert result.warnings == ["쇼핑 API 모의 데이터"]
    assert "제출을 완료" not in result.message


@pytest.mark.parametrize(
    "reason,expected",
    [("STALE_OUTPUT", "STALE_OUTPUT"), ("secret-provider-payload", "PROCESSING_ERROR")],
)
def test_error_diagnostics_keep_safe_code_without_payload(service, caplog, reason, expected):
    session = AgentSession(service, OWNER, ScriptModel(responses=[]))

    class FailedGraph:
        def invoke(self, *args):
            raise ValueError(reason)

    session.graph = FailedGraph()
    result = session.invoke("제출해줘")
    assert expected in result["response"].message
    assert "문의 번호" in result["response"].message
    assert f"code={expected}" in caplog.text
    assert "secret-provider-payload" not in caplog.text + result["response"].message
