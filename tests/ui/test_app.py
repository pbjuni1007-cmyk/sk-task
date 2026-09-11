from datetime import datetime, timezone

from streamlit.testing.v1 import AppTest

from purchase_agent.config import demo_context
from purchase_agent.schemas import (
    CoupangProduct,
    ProductEvidence,
    ProductSupplement,
    RequestInput,
    RequestPatch,
)
from purchase_agent.workflow import LocalPurchaseService


def run_app(service):
    from unittest.mock import patch

    at = AppTest.from_string("from purchase_agent.ui.app import main\nmain()")
    with patch("purchase_agent.ui.app.get_service", return_value=service):
        at.run(timeout=15)
    at._test_service = service
    return at


def rerun(at):
    from unittest.mock import patch

    with patch("purchase_agent.ui.app.get_service", return_value=at._test_service):
        at.run(timeout=15)
    assert not at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    return rerun(at)


def seed(service, purpose="업무", quantity=1):
    owner = demo_context("employee_a", "seed")
    r = service.create_request(
        owner, RequestInput(quantity=quantity, budget_krw=2000000, purpose=purpose), "seed"
    ).data
    service.search_products(owner, r, "monitor")
    r = service.update_request(
        owner, r.request_id, RequestPatch(expected_version=r.version, selected_evidence_id="e1")
    ).data
    service.review_request(owner, r)
    service.generate_documents(owner, r)
    return r, owner


def service_with_products(tmp_path):
    now = datetime.now(timezone.utc)
    catalog = [
        ProductEvidence(
            evidence_id=f"e{i}",
            product=CoupangProduct(
                productId=i,
                productName=f"Synthetic monitor {i}",
                productPrice=280000,
                productUrl=f"https://www.coupang.com/vp/products/{i}",
                productImage="https://example.com/test.png",
                isRocket=False,
                isFreeShipping=True,
                keyword="monitor",
                rank=i,
            ),
            supplement=ProductSupplement(
                product_id=i,
                item_id=str(i),
                vendor_item_id=str(i),
                option_label="QHD",
                verified_specs=["QHD"],
                shipping_rule="free",
                shipping_source_url=f"https://www.coupang.com/vp/products/{i}",
                source_checked_at=now,
                source_status="verified",
            ),
            query="monitor",
            retrieved_at=now,
            fixture_version="test",
        )
        for i in (1, 2)
    ]
    return LocalPurchaseService(tmp_path / "ui.db", catalog)


def test_create_empty_catalog_and_role_isolation(tmp_path):
    service = LocalPurchaseService(tmp_path / "empty.db")
    at = run_app(service)
    assert not at.exception
    click(at, "+ 새 구매요청")
    click(at, "저장하고 상품 찾기")
    assert any("조건은 저장했지만" in w.value for w in at.warning)
    click(at, "후보 검색")
    assert any("실제 상품 자료가 없습니다" in e.value for e in at.error)
    actor_thread = at.session_state["actor_sessions"]["employee_a"]["session_id"]
    at.selectbox(key="profile").select("employee_b")
    rerun(at)
    assert any("처리할 구매요청이 없습니다" in i.value for i in at.info)
    at.selectbox(key="profile").select("employee_a")
    rerun(at)
    assert at.session_state["actor_sessions"]["employee_a"]["session_id"] == actor_thread


def test_missing_purpose_document_tabs_and_disabled_submit(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service, purpose=None)
    at = run_app(service)
    click(at, "열기")
    assert [t.label for t in at.tabs] == ["구매요청서", "상품 비교표", "규정 검토"]
    assert next(b for b in at.button if b.label == "구매팀에 제출").disabled
    assert len(at.get("download_button")) == 3
    assert any("구매 목적" in w.value for w in at.error)
    assert service.get_request(owner, r).data.request.submitted_at is None


def test_explicit_confirmation_cancel_role_change_and_high_approval(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service, quantity=4)
    at = run_app(service)
    click(at, "열기")
    click(at, "구매팀에 제출")
    confirmation = at.session_state["actor_sessions"]["employee_a"]["submission"]["confirmation"]
    assert confirmation.token not in "\n".join(t.value for t in at.text)
    click(at, "취소")
    assert service.get_request(owner, r).data.request.status == "ready"
    click(at, "구매팀에 제출")
    at.selectbox(key="profile").select("employee_b")
    rerun(at)
    at.selectbox(key="profile").select("employee_a")
    rerun(at)
    assert "submission" not in at.session_state["actor_sessions"]["employee_a"]
    click(at, "구매팀에 제출")
    click(at, "제출")
    assert len(service.get_request(owner, r).data.history) == 1
    at.selectbox(key="profile").select("buyer_a")
    rerun(at)
    click(at, "열기")
    click(at, "반려")
    assert at.button(key="confirm_decision").disabled
    assert at.button(key="confirm_decision").label == "반려"
    assert (
        next(t for t in at.text_area if t.label == "처리 의견").proto.placeholder
        == "승인 / 보완 / 반려 사유를 입력해주세요"
    )
    click(at, "처리 취소")
    click(at, "승인")
    assert any("추가 승인자" in i.value for i in at.info)
    at.button(key="confirm_decision").click()
    rerun(at)
    assert service.get_request(owner, r).data.request.status == "additional_approval"
    at.selectbox(key="profile").select("manager_a")
    rerun(at)
    click(at, "열기")
    click(at, "승인")
    at.button(key="confirm_decision").click()
    rerun(at)
    assert service.get_request(owner, r).data.request.status == "approved"


def test_edit_and_search_refresh_use_latest_version(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, "열기")
    click(at, "구매 조건 수정")
    next(t for t in at.text_area if t.label.startswith("구매 목적")).input("새 업무 목적")
    click(at, "구매 조건 저장")
    latest = service.get_latest_request(owner, r.request_id).data
    assert latest.request.version == r.version + 1
    assert latest.documents is None
    service.catalog[0].product.productPrice += 1000
    next(t for t in at.text_input if t.label == "상품 검색어").input("monitor")
    next(c for c in at.checkbox if c.label == "상품 근거 새로 조회").check()
    click(at, "후보 검색")
    latest = service.get_latest_request(owner, r.request_id).data
    assert latest.request.version == r.version + 2
    assert next(s for s in at.selectbox if s.label == "조회 버전").value == latest.request.version
    click(at, "검토하고 문서 만들기 →")
    assert (
        service.get_latest_request(owner, r.request_id).data.review.version
        == latest.request.version
    )
    next(s for s in at.selectbox if s.label == "조회 버전").select(r.version)
    rerun(at)
    assert any("읽기 전용" in w.value for w in at.warning)
    assert not any(b.label == "검토하고 문서 만들기 →" for b in at.button)


def test_create_searches_and_shows_next_step(tmp_path):
    service = service_with_products(tmp_path)
    for evidence in service.catalog:
        evidence.query = "모니터"
    at = run_app(service)
    click(at, "+ 새 구매요청")
    assert any(t.proto.placeholder.startswith("예:") for t in at.text_area)
    click(at, "저장하고 상품 찾기")
    assert any("step active" in m.value and "상품 선택" in m.value for m in at.markdown)
    assert any(b.label == "이 상품 선택" for b in at.button)
    assert not at.tabs
    assert not any(t.label.startswith("구매 목적") for t in at.text_area)
    state = at.session_state["actor_sessions"]["employee_a"]
    detail = service.get_latest_request(
        demo_context("employee_a", state["session_id"]), state["request_id"]
    ).data
    assert len(detail.candidates) == 2
    assert detail.request.selected_evidence_id is None
    assert detail.request.submitted_at is None
    click(at, "이 상품 선택")
    click(at, "검토하고 문서 만들기 →")
    assert any("step active" in m.value and "검토 및 제출" in m.value for m in at.markdown)
    assert not any(b.label == "이 상품 선택" for b in at.button)
    click(at, "← 상품 선택")
    assert any(b.label == "이 상품 선택" for b in at.button)
    assert not at.tabs


def test_new_purchase_resets_draft_but_preserves_existing_conversation(tmp_path):
    service = service_with_products(tmp_path)
    at = run_app(service)
    state = at.session_state["actor_sessions"]["employee_a"]
    state.update(
        draft_chat={"history": [("user", "저장 전 대화")]},
        conversations={"old-request": {"history": [("user", "이전 요청")]}},
        request_id="old-request",
        submission={"kind": "manual"},
        decision={"decision": "approve"},
        phase=3,
    )
    old_create_id = state["create_id"]
    click(at, "+ 새 구매요청")
    assert state["view"] == "create"
    assert state["request_id"] is None
    assert state["create_id"] != old_create_id
    assert not state.get("draft_chat", {}).get("history")
    assert state["conversations"]["old-request"]["history"] == [("user", "이전 요청")]
    assert not state.get("submission")
    assert not state.get("decision")


def test_navigation_and_reopening_existing_request_preserve_ai_state(tmp_path):
    service = service_with_products(tmp_path)
    r, _ = seed(service)
    at = run_app(service)
    click(at, "열기")
    state = at.session_state["actor_sessions"]["employee_a"]
    chat = state["conversations"][r.request_id]
    chat.update(agent="existing-agent", history=[("user", "계속할 요청")])
    click(at, "내 구매요청")
    click(at, "열기")
    assert state["request_id"] == r.request_id
    assert chat["agent"] == "existing-agent"
    assert chat["history"] == [("user", "계속할 요청")]
    assert any(t.value == "계속할 요청" for t in at.text)


def test_price_preference_orders_visible_candidates(tmp_path):
    service = service_with_products(tmp_path)
    service.catalog[1].product.productPrice = 200000
    ref, owner = seed(service)
    service.save_preferences(owner, {"comparison_priority": "price"}, consent=True)
    at = run_app(service)
    click(at, "열기")
    click(at, "← 상품 선택")
    products = [t.value for t in at.text if t.value.startswith("Synthetic monitor")]
    assert products[0].startswith("Synthetic monitor 2")


def test_stale_submission_cannot_submit_changed_document(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, "열기")
    click(at, "구매팀에 제출")
    service.update_request(
        owner, r.request_id, RequestPatch(expected_version=r.version, quantity=2)
    )
    rerun(at)
    assert next(b for b in at.button if b.label == "제출").disabled
    assert any("바뀌었습니다" in w.value for w in at.warning)
    assert service.get_latest_request(owner, r.request_id).data.request.status == "draft"
    click(at, "취소")


def test_revision_reason_and_requester_resume(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service)
    detail = service.get_request(owner, r).data
    service.submit_request(
        owner, service.prepare_submission(owner, r, detail.documents.bundle_id).data
    )
    at = run_app(service)
    at.selectbox(key="profile").select("buyer_a")
    rerun(at)
    click(at, "열기")
    assert not any(t.label == "AI 요청" for t in at.text_area)
    click(at, "보완 요청")
    assert at.button(key="confirm_decision").disabled
    next(t for t in at.text_area if t.label == "처리 의견").input(
        "사용 부서를 구체적으로 적어 주세요"
    )
    rerun(at)
    at.button(key="confirm_decision").click()
    rerun(at)
    at.selectbox(key="profile").select("employee_a")
    rerun(at)
    click(at, "열기")
    assert any(t.value == "사용 부서를 구체적으로 적어 주세요" for t in at.text)
    click(at, "구매 조건 보완")
    next(t for t in at.text_area if t.label.startswith("구매 목적")).input("개발팀 신규 장비")
    click(at, "구매 조건 저장")
    click(at, "검토하고 문서 만들기 →")
    click(at, "구매팀에 제출")
    click(at, "제출")
    latest = service.get_latest_request(owner, r.request_id).data
    assert latest.request.status == "submitted"
    assert latest.request.version == r.version + 1


def test_ai_and_manual_share_confirmation_and_request_history(tmp_path):
    from unittest.mock import patch

    from langchain_core.messages import AIMessage
    from test_agent import answer
    from test_s0_langchain import ScriptModel

    from purchase_agent.agent import AgentSession

    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, "열기")
    state = at.session_state["actor_sessions"]["employee_a"]
    docs = service.get_request(owner, r).data.documents
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
    chat = state["conversations"][r.request_id]
    chat["agent"] = AgentSession(service, demo_context("employee_a", state["session_id"]), model)
    with patch("purchase_agent.ui.chat.model_available", return_value=True):
        rerun(at)
        next(t for t in at.text_area if t.label == "AI 요청").input("제출해줘")
        click(at, "AI에게 요청")
        assert state["submission"]["kind"] == "ai"
        assert service.get_request(owner, r).data.request.status == "ready"
        click(at, "취소")
        assert service.get_request(owner, r).data.request.status == "ready"
        assert any("취소" in text for _, text in chat["history"])
        click(at, "내 구매요청")
        click(at, "열기")
        assert any(t.value == "제출해줘" for t in at.text)
        click(at, "구매팀에 제출")
        assert state["submission"]["kind"] == "manual"
        click(at, "제출")
        assert service.get_request(owner, r).data.request.status == "submitted"


def test_manual_version_change_resets_execution_keeps_chat(tmp_path):
    service = service_with_products(tmp_path)
    r, _ = seed(service)
    at = run_app(service)
    click(at, "열기")
    chat = at.session_state["actor_sessions"]["employee_a"]["conversations"][r.request_id]
    chat.update(agent="old execution", history=[("user", "기존 조건")])
    click(at, "구매 조건 수정")
    next(t for t in at.text_area if t.label.startswith("구매 목적")).input("변경된 목적")
    click(at, "구매 조건 저장")
    assert "agent" not in chat
    assert chat["history"] == [("user", "기존 조건")]
    click(at, "← 구매 조건")
    assert next(t for t in at.text_area if t.label.startswith("구매 목적")).value == "변경된 목적"


def test_ai_submission_approve_and_old_version_readonly(tmp_path):
    from unittest.mock import patch

    from langchain_core.messages import AIMessage
    from test_agent import answer
    from test_s0_langchain import ScriptModel

    from purchase_agent.agent import AgentSession

    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, "열기")
    state = at.session_state["actor_sessions"]["employee_a"]
    docs = service.get_request(owner, r).data.documents
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
    state["conversations"][r.request_id]["agent"] = AgentSession(
        service, demo_context("employee_a", state["session_id"]), model
    )
    with patch("purchase_agent.ui.chat.model_available", return_value=True):
        rerun(at)
        next(t for t in at.text_area if t.label == "AI 요청").input("제출해줘")
        click(at, "AI에게 요청")
        click(at, "제출")
        assert service.get_request(owner, r).data.request.status == "submitted"
        assert sum(e.decision == "submit" for e in service.get_request(owner, r).data.history) == 1
        next(s for s in at.selectbox if s.label == "조회 버전").select(1)
        rerun(at)
        assert not any(t.label == "AI 요청" for t in at.text_area)
        assert not any(b.label == "구매팀에 제출" for b in at.button)


def test_ai_updates_existing_form_and_draft_creation_isolated(tmp_path):
    from unittest.mock import patch

    from langchain_core.messages import AIMessage
    from test_agent import answer
    from test_s0_langchain import ScriptModel

    from purchase_agent.agent import AgentSession

    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, "열기")
    click(at, "구매 조건 수정")
    state = at.session_state["actor_sessions"]["employee_a"]
    model = ScriptModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "upsert_purchase_request",
                        "args": {
                            "request_id": r.request_id,
                            "expected_version": r.version,
                            "quantity": 2,
                        },
                        "id": "update",
                    }
                ],
            ),
            answer(request_id=r.request_id, version=r.version + 1),
        ]
    )
    state["conversations"][r.request_id]["agent"] = AgentSession(
        service, demo_context("employee_a", state["session_id"]), model
    )
    with patch("purchase_agent.ui.chat.model_available", return_value=True):
        rerun(at)
        next(t for t in at.text_area if t.label == "AI 요청").input("수량을 2대로 바꿔줘")
        click(at, "AI에게 요청")
        assert service.get_latest_request(owner, r.request_id).data.request.inputs.quantity == 2
        click(at, "← 구매 조건")
        assert next(n for n in at.number_input if n.label == "수량").value == 2
        click(at, "+ 새 구매요청")
        assert not any(t.value == "수량을 2대로 바꿔줘" for t in at.text)
        new_model = ScriptModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "upsert_purchase_request",
                            "args": {
                                "quantity": 1,
                                "budget_krw": 500000,
                                "purpose": "AI 신규 요청",
                            },
                            "id": "create",
                        }
                    ],
                ),
                answer(),
            ]
        )
        state["draft_chat"]["agent"] = AgentSession(
            service, demo_context("employee_a", state["session_id"]), new_model
        )
        next(t for t in at.text_area if t.label == "AI 요청").input(
            "모니터 1대 50만원으로 새 요청 만들어줘"
        )
        click(at, "AI에게 요청")
        new_id = state["request_id"]
        assert new_id != r.request_id
        assert (
            state["conversations"][new_id]["history"][0][1]
            == "모니터 1대 50만원으로 새 요청 만들어줘"
        )
        assert state["conversations"][r.request_id]["history"][0][1] == "수량을 2대로 바꿔줘"


def test_recent_requests_and_user_text_are_displayed_safely(tmp_path):
    service = service_with_products(tmp_path)
    _, owner = seed(service)
    purpose = "<img src=x onerror=alert(1)> **구매**"
    latest = service.create_request(
        owner, RequestInput(quantity=1, budget_krw=300000, purpose=purpose), "latest"
    ).data
    at = run_app(service)
    click(at, "내 구매요청")
    click(at, "열기")
    state = at.session_state["actor_sessions"]["employee_a"]
    assert state["request_id"] == latest.request_id
    # Dynamic text must never be interpolated into trusted HTML without escaping.
    assert not any("<img src=x" in m.value for m in at.markdown)
    assert any(purpose == c.value for c in at.text)


def test_document_rendering_and_korean_approval_history(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service)
    d = service.get_request(owner, r).data
    service.submit_request(owner, service.prepare_submission(owner, r, d.documents.bundle_id).data)
    at = run_app(service)
    click(at, "열기")
    assert any(m.value.startswith("# 구매요청서") for m in at.markdown)
    assert any("구매요청 제출" in m.value for m in at.markdown)
    assert any("박직원 · 개발팀" in t.value and "버전" in t.value for t in at.text)
    assert not any("employee_a · submit" in t.value for t in at.text)
