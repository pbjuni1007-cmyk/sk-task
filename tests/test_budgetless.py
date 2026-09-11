from langchain_core.messages import AIMessage
from test_agent import answer
from test_s0_langchain import ScriptModel
from test_workflow import OWNER
from test_workflow import catalog as catalog  # noqa: F401
from test_workflow import service as service  # noqa: F401

from purchase_agent.agent import AgentSession
from purchase_agent.config import demo_context
from purchase_agent.schemas import ListQuery
from purchase_agent.tools import build_tools


def call(name, args, ident):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": ident}])


def test_budgetless_search_preserves_quantity_and_creates_no_request(service):
    model = ScriptModel(
        responses=[
            call(
                "upsert_purchase_request", {"quantity": 1, "purpose": "부장님 모니터 교체"}, "draft"
            ),
            call(
                "search_coupang_products", {"keyword": "monitor", "sort_by": "price_desc"}, "search"
            ),
            answer(status="candidates_ready", candidate_ids=[999999]),
        ]
    )
    session = AgentSession(service, OWNER, model)
    result = session.invoke("부장님 모니터 제일 비싼 걸로 1개 요청서 만들어줘")
    assert session.current_request is None
    assert session.draft_inputs["quantity"] == 1
    assert session.explored
    assert result["response"].missing_fields == ["budget_krw"]
    assert "1대" in result["response"].message
    assert service.list_requests(OWNER, ListQuery(folder="mine")).data.total == 0
    # 후속 팀 예산 지시는 앞선 문서 생성 의도를 이어갈 수 있다.
    session.model.inner.responses.extend(
        [
            call("get_department_budget", {}, "budget"),
            call("upsert_purchase_request", {"use_department_budget": True}, "create"),
            answer(),
        ]
    )
    session.invoke("우리 팀 예산으로 제일 비싼 걸 검색해서 해줘")
    detail = service.get_latest_request(OWNER, session.current_request).data
    assert detail.request.inputs.quantity == 1
    assert detail.request.inputs.budget_krw == 500000
    assert not session.search_only


def test_mock_budget_context_is_scoped_and_requires_user_intent(service):
    session = AgentSession(service, OWNER, ScriptModel(responses=[]))
    tool = next(t for t in build_tools(session) if t.name == "upsert_purchase_request")
    result = tool.invoke({"quantity": 1, "use_department_budget": True})
    assert result["error_code"] == "DEPARTMENT_BUDGET_NOT_REQUESTED"
    a = service.get_department_budget(OWNER).data
    b = service.get_department_budget(demo_context("employee_b", "test")).data
    assert a["department_id"] != b["department_id"]
    assert a["available_krw"] == 500000 and b["available_krw"] == 300000
    forged = OWNER.model_copy(update={"department_id": "operations"})
    assert not service.get_department_budget(forged).ok


def test_explicit_amount_is_not_overridden_by_team_budget(service):
    session = AgentSession(service, OWNER, ScriptModel(responses=[]))
    session.department_budget_requested = True
    tool = next(t for t in build_tools(session) if t.name == "upsert_purchase_request")
    result = tool.invoke({"quantity": 1, "budget_krw": 100000, "use_department_budget": True})
    assert result["ok"] and result["data"]["inputs"]["budget_krw"] == 100000


def test_catalog_extreme_sort_applies_before_limit(service):
    original = service.catalog[0]
    service.catalog = []
    for i in range(12):
        e = original.model_copy(deep=True)
        e.evidence_id = f"test-{i}"
        e.product.productPrice = (i + 1) * 10000
        service.catalog.append(e)
    result = service.explore_products(OWNER, "monitor", limit=3, sort_by="price_desc")
    assert result.ok
    assert [e.product.productPrice for e in result.data] == [120000, 110000, 100000]
    assert not service.explore_products(OWNER, "monitor", sort_by="bad").ok


def test_explored_candidates_transfer_to_created_request(service):
    session = AgentSession(service, OWNER, ScriptModel(responses=[]))
    tools = {t.name: t for t in build_tools(session)}
    explored = tools["search_coupang_products"].invoke(
        {"keyword": "monitor", "sort_by": "price_desc"}
    )
    selected = explored["data"]["candidates"][0]["evidence_id"]
    created = tools["upsert_purchase_request"].invoke({"quantity": 1, "budget_krw": 500000})
    r = created["data"]
    result = tools["upsert_purchase_request"].invoke(
        {
            "request_id": r["request_id"],
            "expected_version": r["version"],
            "selected_evidence_id": selected,
        }
    )
    assert result["ok"]
    assert result["data"]["selected_evidence_id"] == selected


def test_catalog_has_supplied_models_and_corrected_seller():
    import json
    from pathlib import Path

    from purchase_agent.catalog import load_catalog

    evidence = load_catalog()
    assert len(evidence) == 12
    source = json.loads(Path("fixtures/coupang/user-provided-products.json").read_text())
    assert len(source["products"]) == 12
    lg = next(e for e in evidence if e.product.productId == 3512529)
    assert "LG전자" in lg.product.productName
    assert lg.product.productPrice == 63350
    assert "24MP58VQ" in str(lg.model_dump())
    row = next(p for p in source["products"] if "3512529" in str(p))
    assert row["seller"] == "LG전자"
