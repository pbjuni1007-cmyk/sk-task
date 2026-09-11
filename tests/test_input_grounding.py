"""모델이 누락 조건·상품 선택을 임의로 채우지 못하도록 실행 경계를 검사한다."""

import pytest
from test_agent import answer
from test_budgetless import call
from test_s0_langchain import ScriptModel
from test_workflow import OWNER
from test_workflow import catalog as catalog  # noqa: F401
from test_workflow import service as service  # noqa: F401

from purchase_agent.agent import AgentSession
from purchase_agent.schemas import ListQuery, RequestInput


@pytest.mark.parametrize("invented", [{"quantity": 1}, {"quantity": 1, "budget_krw": 500000}])
def test_missing_conditions_cannot_be_invented(service, invented):
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(responses=[call("upsert_purchase_request", invented, "invented"), answer()]),
    )
    response = session.invoke("모니터 구매요청서 써줘.")["response"]
    assert service.list_requests(OWNER, ListQuery()).data.total == 0
    assert not session.draft_inputs.get("quantity")
    assert not session.draft_inputs.get("budget_krw")
    assert response.missing_fields == ["quantity", "budget_krw"]


def test_document_request_does_not_authorize_product_selection(service):
    ref = service.create_request(OWNER, RequestInput(quantity=3, budget_krw=900000), "new").data
    service.search_products(OWNER, ref, "monitor")
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call(
                    "upsert_purchase_request",
                    {
                        "request_id": ref.request_id,
                        "expected_version": ref.version,
                        "selected_evidence_id": "e1",
                    },
                    "select",
                ),
                answer(request_id=ref.request_id, version=ref.version),
            ]
        ),
    )
    session.invoke("모니터 구매요청서 써줘.", request_id=ref.request_id)
    detail = service.get_latest_request(OWNER, ref.request_id).data
    assert detail.request.selected_evidence_id is None
    assert detail.documents is None


@pytest.mark.parametrize(
    "text,quantity,budget",
    [
        ("모니터3대, 예산60만원", 3, 600000),
        ("모니터 두 대, 배송비 포함 50만 원", 2, 500000),
        ("수량: 4, 예산: 1,200,000", 4, 1200000),
    ],
)
def test_explicit_conditions_can_be_saved(service, text, quantity, budget):
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call(
                    "upsert_purchase_request",
                    {"quantity": quantity, "budget_krw": budget},
                    "create",
                ),
                answer(),
            ]
        ),
    )
    session.invoke(text)
    detail = service.get_latest_request(OWNER, session.current_request).data
    assert detail.request.inputs.quantity == quantity
    assert detail.request.inputs.budget_krw == budget


def test_specification_and_document_counts_are_not_quantity(service):
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[call("upsert_purchase_request", {"quantity": 3}, "invented"), answer()]
        ),
    )
    session.invoke("27인치 모니터 구매 문서 3종 만들어줘")
    assert not session.draft_inputs.get("quantity")


@pytest.mark.parametrize(
    "instruction,allowed",
    [
        ("이 상품 선택해서 작성해줘", True),
        ("예산 안에서 제일 비싼 걸 골라줘", True),
        ("선택하지 말고 후보만 보여줘", False),
        ("상품 선택은 내가 할게. 문서 작성 준비해줘", False),
    ],
)
def test_product_selection_requires_explicit_instruction(service, instruction, allowed):
    ref = service.create_request(OWNER, RequestInput(quantity=3, budget_krw=900000), "new").data
    service.search_products(OWNER, ref, "monitor")
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call(
                    "upsert_purchase_request",
                    {
                        "request_id": ref.request_id,
                        "expected_version": ref.version,
                        "selected_evidence_id": "e1",
                    },
                    "select",
                ),
                answer(),
            ]
        ),
    )
    session.invoke(instruction, request_id=ref.request_id)
    detail = service.get_latest_request(OWNER, ref.request_id).data
    assert (detail.request.selected_evidence_id == "e1") is allowed


def test_quantity_only_followup_preserves_budget_and_selection(service):
    from test_workflow import ready

    ref, _, _ = ready(service)
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call(
                    "upsert_purchase_request",
                    {
                        "request_id": ref.request_id,
                        "expected_version": ref.version,
                        "quantity": 4,
                        "budget_krw": 900000,
                        "selected_evidence_id": "e1",
                    },
                    "update",
                ),
                answer(),
            ]
        ),
    )
    session.invoke("선택 상품과 목적은 유지하고 수량만 4대로 바꿔줘", request_id=ref.request_id)
    detail = service.get_latest_request(OWNER, ref.request_id).data
    assert detail.request.inputs.quantity == 4
    assert detail.request.inputs.budget_krw == 900000
    assert detail.request.selected_evidence_id == "e1"


@pytest.mark.parametrize(
    "instruction",
    [
        "선택 상품과 목적은 유지하고 문서 만들어줘",
        "제일 비싼 상품이 뭔지 알려줘",
    ],
)
def test_reference_to_selection_or_price_is_not_delegation(service, instruction):
    from test_workflow import ready

    ref, _, _ = ready(service)
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call(
                    "upsert_purchase_request",
                    {
                        "request_id": ref.request_id,
                        "expected_version": ref.version,
                        "selected_evidence_id": "e2",
                    },
                    "switch",
                ),
                answer(),
            ]
        ),
    )
    session.invoke(instruction, request_id=ref.request_id)
    assert (
        service.get_latest_request(OWNER, ref.request_id).data.request.selected_evidence_id == "e1"
    )


def test_partial_answer_survives_without_an_upsert_call(service):
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                answer(),
                call("upsert_purchase_request", {"quantity": 3, "budget_krw": 600000}, "create"),
                answer(),
            ]
        ),
    )
    session.invoke("모니터 3대가 필요해")
    session.invoke("예산은 60만원이야")
    detail = service.get_latest_request(OWNER, session.current_request).data
    assert detail.request.inputs.quantity == 3
    assert detail.request.inputs.budget_krw == 600000


def test_requested_department_budget_is_a_grounded_value(service):
    session = AgentSession(
        service,
        OWNER,
        ScriptModel(
            responses=[
                call("get_department_budget", {}, "budget"),
                call("upsert_purchase_request", {"quantity": 1, "budget_krw": 500000}, "create"),
                answer(),
            ]
        ),
    )
    session.invoke("모니터 1대, 우리 팀 예산으로 요청서 만들어줘")
    detail = service.get_latest_request(OWNER, session.current_request).data
    assert detail.request.inputs.budget_krw == 500000
