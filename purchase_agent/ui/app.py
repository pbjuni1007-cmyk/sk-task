"""구매 화면. 직접 입력과 AI 입력이 같은 LocalPurchaseService를 사용한다."""

import os
from datetime import datetime, time, timezone
from pathlib import Path
from uuid import uuid4

import streamlit as st

from purchase_agent.catalog import load_catalog
from purchase_agent.config import DEMO_PROFILES, demo_context
from purchase_agent.policy import shipping_total
from purchase_agent.schemas import ListQuery, RequestInput, RequestPatch, RequestRef
from purchase_agent.ui.chat import panel as chat_panel
from purchase_agent.ui.confirmations import show_confirmation
from purchase_agent.ui.presentation import (
    DOCS,
    PROFILES,
    ROLES,
    badge,
    document_preview,
    heading,
    money,
    progress,
    steps,
    style,
)
from purchase_agent.ui.state import clear_confirmations, deactivate, navigate, new_purchase
from purchase_agent.workflow import LocalPurchaseService

ROOT = Path(__file__).resolve().parents[2]

FOLDERS = dict(mine="내 구매요청", pending="결재 대기", revision="보완 요청", completed="완료 문서")
ERRORS = {
    "CATALOG_NOT_VERIFIED": "확인된 실제 상품 자료가 없습니다. 상품·옵션·판매자·배송 근거를 준비한 뒤 다시 검색해 주세요.",
    "STALE_VERSION": "다른 작업에서 새 버전이 만들어졌습니다. 최신 요청을 다시 열어 주세요.",
    "NOT_READY": "제출 조건이 충족되지 않았습니다. 누락 항목을 보완하고 문서를 다시 검토해 주세요.",
    "FORBIDDEN": "이 요청에 접근할 권한이 없습니다. 내 요청함으로 돌아가 주세요.",
    "CONFIRMATION_EXPIRED": "제출 확인이 만료되었습니다. 최신 문서에서 제출 확인을 다시 열어 주세요.",
    "STORAGE_ERROR": "저장소 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.",
}


@st.cache_resource
def get_service(path):
    """One service boot identity across reruns and sessions for this DB path."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return LocalPurchaseService(path, catalog=load_catalog(ROOT / "fixtures/coupang"))


def result_data(result):
    if not result.ok:
        st.error(
            ERRORS.get(
                result.error_code,
                "처리할 수 없습니다. 입력·권한·최신 버전을 확인한 뒤 다시 시도해 주세요.",
            )
        )
        return None
    return result.data


def ref_of(request):
    return RequestRef(request_id=request.request_id, version=request.version)


def move(state, view, request_id=None):
    navigate(state, view, request_id)
    st.rerun()


def start_new_purchase(state):
    new_purchase(state)
    st.rerun()


def inputs_form(inputs, key, submit_label="구매 조건 저장"):
    with st.form(key):
        a, b = st.columns(2)
        quantity = a.number_input(
            "수량", min_value=1, max_value=20, value=inputs.quantity, key=f"{key}_quantity"
        )
        budget = b.number_input(
            "예산 · 배송비 포함 (원)",
            min_value=1,
            value=inputs.budget_krw,
            step=10000,
            key=f"{key}_budget",
        )
        requirements = st.text_area(
            "희망 사양 · 한 줄에 하나",
            value="\n".join(inputs.requirements),
            key=f"{key}_requirements",
            placeholder="예: 27인치\nFHD\nUSB-C 연결",
        )
        purpose = st.text_area(
            "구매 목적 · 제출 전 필수",
            value=inputs.purpose or "",
            key=f"{key}_purpose",
            max_chars=500,
            placeholder="예: 신규 입사자 3명의 업무용 모니터 지급",
        )
        saved = st.form_submit_button(submit_label, type="primary")
    if saved:
        return RequestInput(
            quantity=quantity,
            budget_krw=budget,
            requirements=[s.strip() for s in requirements.splitlines() if s.strip()],
            purpose=purpose,
        )
    return None


def create_screen(service, context, state):
    heading(
        "새 구매요청", "필요한 상품과 예산을 알려주세요. AI 도우미에게 문장으로 요청해도 됩니다."
    )
    steps(1)
    show_ai = st.toggle("AI 도우미", value=True, key="show_ai_create")
    columns = st.columns([7, 3], gap="large") if show_ai else [st.container()]
    with columns[0]:
        values = inputs_form(
            RequestInput(quantity=1, budget_krw=300000),
            f"create_{state['create_id']}",
            "저장하고 상품 찾기",
        )
        st.caption("구매 목적은 제출 전까지 입력하면 됩니다.")
        if values:
            request = result_data(service.create_request(context, values, state["create_id"]))
            if request:
                with st.spinner("조건을 저장하고 상품을 찾는 중…"):
                    found = service.search_products(context, ref_of(request), "모니터")
                if not found.ok or not found.data:
                    state["search_notice"] = (
                        "조건은 저장했지만 상품을 찾지 못했습니다. 검색 조건을 바꿔 다시 검색해 주세요."
                    )
                else:
                    state["notice"] = "조건을 저장했습니다. 구매할 상품을 선택하세요."
                move(state, "detail", request.request_id)
    if show_ai:
        with columns[1]:
            chat_panel(service, context, state)


def request_rows(items, state, prefix):
    for detail in items:
        r = detail.request
        with st.container(border=True):
            row = st.columns([5, 2, 2, 1])
            row[0].text(r.inputs.purpose or "모니터 구매 · 목적 입력 필요")
            row[0].caption(f"{PROFILES.get(r.owner_id, r.owner_id)} · {r.inputs.quantity}대")
            row[1].text(money(detail.review.review_total_krw if detail.review else None))
            with row[2]:
                badge(r.status)
            if row[3].button("열기", key=f"{prefix}_{r.request_id}"):
                move(state, "detail", r.request_id)


def home_screen(service, context, state):
    heading(
        "내 업무",
        f"{PROFILES.get(context.actor_id, context.actor_id)} · 지금 처리할 구매요청을 확인하세요.",
    )
    folder = "mine" if context.role == "requester" else "pending"
    page = result_data(service.list_requests(context, ListQuery(folder=folder, page_size=100)))
    if page is None:
        return
    actionable = (
        [d for d in page.items if d.request.status in ("draft", "ready", "needs_revision")]
        if folder == "mine"
        else page.items
    )
    st.subheader("내가 처리할 요청")
    if actionable:
        request_rows(actionable[:5], state, "todo")
    else:
        st.info(
            "처리할 구매요청이 없습니다. 새 구매요청을 작성해 보세요."
            if folder == "mine"
            else "현재 대기 중인 결재가 없습니다."
        )
    if len(actionable) > 5 or page.total > 100:
        st.caption("일부 요청을 표시하고 있습니다. 전체 목록에서 나머지 요청을 확인하세요.")
    if st.button("전체 요청 보기"):
        state.update(folder=folder, page=1)
        move(state, "list")
    recent = result_data(service.list_requests(context, ListQuery(folder="mine", page_size=5)))
    if recent and recent.items:
        st.subheader("최근 구매요청")
        st.caption("최근 생성한 내 요청 5건")
        request_rows(recent.items, state, "recent")


def list_screen(service, context, state):
    st.header(FOLDERS[state["folder"]])
    with st.form("filters"):
        cols = st.columns(4)
        keyword = cols[0].text_input("요청번호 또는 제목")
        department = cols[1].selectbox(
            "부서",
            ["", *sorted({v[0] for v in DEMO_PROFILES.values()})],
            format_func=lambda x: x or "전체 부서",
        )
        start = cols[2].date_input("제출일 시작", value=None)
        end = cols[3].date_input("제출일 종료", value=None)
        if st.form_submit_button("조회"):
            state["page"] = 1
    if start and end and start > end:
        st.error("시작일은 종료일보다 늦을 수 없습니다.")
        return
    query = ListQuery(
        folder=state["folder"],
        keyword=keyword,
        department_id=department or None,
        date_from=datetime.combine(start, time.min, tzinfo=timezone.utc) if start else None,
        date_to=datetime.combine(end, time.max, tzinfo=timezone.utc) if end else None,
        page=state["page"],
        page_size=10,
    )
    page = result_data(service.list_requests(context, query))
    if page is None:
        return
    st.caption(f"총 {page.total}건 · {state['page']}페이지")
    if not page.items:
        st.info("처리할 구매요청이 없습니다. 검색 조건이 있다면 비우고 다시 조회해 주세요.")
    request_rows(page.items, state, "list")
    a, b = st.columns(2)
    if a.button("이전 페이지", disabled=state["page"] <= 1):
        state["page"] -= 1
        st.rerun()
    if b.button("다음 페이지", disabled=state["page"] * 10 >= page.total):
        state["page"] += 1
        st.rerun()


def candidates_screen(service, context, state, detail):
    from purchase_agent.preferences import order_candidates

    preferences = service.get_preferences(context)
    detail = detail.model_copy(
        update={
            "candidates": order_candidates(
                detail.candidates, preferences.data if preferences.ok else {}, detail.request.inputs
            )
        }
    )
    r = detail.request
    if "search" in detail.allowed_actions:
        with (
            st.expander("검색 조건 변경 · 다시 검색", expanded=not bool(detail.candidates)),
            st.form(f"search_{r.version}"),
        ):
            keyword = st.text_input("상품 검색어", value="모니터")
            refresh = st.checkbox("상품 근거 새로 조회")
            search = st.form_submit_button("후보 검색")
        if search:
            if not keyword.strip():
                st.error("검색어를 입력해 주세요.")
            else:
                with st.spinner("후보 검색 중…"):
                    found = result_data(
                        service.search_products(context, ref_of(r), keyword, refresh=refresh)
                    )
                if found is not None:
                    # Search may have created a version; never reuse the displayed ref.
                    latest = result_data(service.get_latest_request(context, r.request_id))
                    if latest:
                        clear_confirmations(state)
                        state["notice"] = (
                            "검색 결과가 없습니다. 검색 조건을 바꿔 주세요."
                            if not found
                            else "후보를 검색했습니다."
                        )
                        st.rerun()
    if not detail.candidates:
        st.info("후보가 없습니다. 확인된 상품 자료를 검색한 뒤 선택해 주세요.")
        return
    rows = []
    for e in detail.candidates:
        fee = shipping_total(e.supplement, r.inputs.quantity)
        total = None if fee is None else e.product.productPrice * r.inputs.quantity + fee
        rows.append(
            {
                "상품": e.product.productName,
                "옵션": e.supplement.option_label or "확인 필요",
                "단가": money(e.product.productPrice),
                "수량별 배송비": money(fee),
                "총액": money(total),
                "예산": "확인 필요"
                if total is None
                else ("이내" if total <= r.inputs.budget_krw else "초과"),
                "상품 링크": str(e.product.productUrl),
            }
        )
    with st.expander("상품 정보 출처"):
        st.caption(
            "사용자 확인 자료를 사용하는 모의 검색입니다. 가격과 배송 조건은 실시간 정보가 아닙니다."
        )
        for e in detail.candidates:
            st.text(f"{e.product.productName} · 확인 기록 {e.supplement.source_checked_at}")
    import json

    source_path = ROOT / "fixtures/coupang/user-provided-products.json"
    sellers = {}
    if source_path.exists():
        sellers = {
            r["productId"]: r["seller"] for r in json.loads(source_path.read_text())["products"]
        }
    for e, row in zip(detail.candidates, rows):
        with st.container(border=True):
            picture, info, choose = st.columns([1, 3, 2])
            picture.image(str(e.product.productImage), width=120)
            info.text(e.product.productName)
            info.caption(f"{row['옵션']} · 판매자 {sellers.get(e.product.productId, '확인 필요')}")
            info.link_button("쿠팡 상품 보기", str(e.product.productUrl))
            choose.markdown(f"**{r.inputs.quantity}대 총액 {row['총액']}**")
            choose.caption(f"배송비 포함 · 예산 {row['예산']}")
            selected = r.selected_evidence_id == e.evidence_id
            if "update" in detail.allowed_actions and choose.button(
                "선택됨" if selected else "이 상품 선택",
                key=f"choose_{r.request_id}_{r.version}_{e.evidence_id}",
                disabled=selected,
                type="primary" if selected else "secondary",
            ):
                updated = result_data(
                    service.update_request(
                        context,
                        r.request_id,
                        RequestPatch(
                            expected_version=r.version, selected_evidence_id=e.evidence_id
                        ),
                    )
                )
                if updated:
                    clear_confirmations(state)
                    st.rerun()
            with st.expander("가격·사양 상세"):
                st.text(f"단가 {row['단가']} · 수량별 배송비 {row['수량별 배송비']}")
                st.text("확인된 사양: " + (" · ".join(e.supplement.verified_specs) or "확인 필요"))


def document_tabs(service, context, detail):
    r = detail.request
    show_history = bool(detail.history or r.submitted_at)
    tabs = st.tabs([*DOCS.values(), *(["결재 이력"] if show_history else [])])
    for tab, (kind, label) in zip(tabs, DOCS.items()):
        with tab:
            if detail.documents and kind in detail.documents.files:
                # Plain text keeps both product text and generated Markdown inert.
                document_preview(detail, kind)
                with st.expander("저장된 문서 원문"):
                    st.text(detail.documents.files[kind])
                data = result_data(service.download_document(context, ref_of(r), kind))
                if data is not None:
                    st.download_button(
                        f"{label} 다운로드",
                        data,
                        file_name=f"{r.request_id}_v{r.version}_{kind}.md",
                        mime="text/markdown",
                    )
            else:
                st.info("문서 초안이 아직 없습니다.")
            if kind == "review" and detail.review:
                with st.expander("규정 검토 상세"):
                    st.dataframe(
                        [c.model_dump() for c in detail.review.checks],
                        hide_index=True,
                        width="stretch",
                    )
    if show_history:
        with tabs[3]:
            if not detail.history:
                st.info("이 버전의 결재 이력이 없습니다.")
            for event in detail.history:
                st.text(
                    f"{event.created_at.isoformat(timespec='minutes')} · {event.actor_id} · {event.decision} · {event.reason or '—'}"
                )


def action_panel(service, context, state, detail):
    r = detail.request
    if (
        "update" in detail.allowed_actions
        and r.owner_id == context.actor_id
        and r.status
        in (
            "draft",
            "ready",
            "needs_revision",
            "rejected",
        )
    ):
        can_submit = "submit" in detail.allowed_actions and bool(
            detail.review
            and detail.review.can_submit
            and detail.documents
            and detail.documents.complete
        )
        if st.button("구매팀에 제출", disabled=not can_submit, type="primary"):
            confirmation = result_data(
                service.prepare_submission(context, ref_of(r), detail.documents.bundle_id)
            )
            if confirmation:
                state["submission"] = dict(
                    kind="manual",
                    request_id=r.request_id,
                    version=r.version,
                    bundle_id=detail.documents.bundle_id,
                    confirmation=confirmation,
                )
    decisions = [
        d for d in ("approve", "request_revision", "reject") if d in detail.allowed_actions
    ]
    if decisions:
        names = dict(approve="승인", reject="반려", request_revision="보완 요청")
        for column, decision in zip(st.columns(len(decisions)), decisions):
            if column.button(
                names[decision],
                type="primary" if decision == "approve" else "secondary",
                width="stretch",
            ):
                state["decision"] = dict(
                    request_id=r.request_id, version=r.version, decision=decision
                )


def detail_body(service, context, state, detail, phase):
    r = detail.request
    editable = "update" in detail.allowed_actions
    if phase == 1:
        values = inputs_form(r.inputs, f"edit_{r.request_id}_{r.version}")
        if values:
            updated = result_data(
                service.update_request(
                    context,
                    r.request_id,
                    RequestPatch(
                        expected_version=r.version, **values.model_dump(exclude={"item_type"})
                    ),
                )
            )
            if updated:
                clear_confirmations(state)
                state["phase"] = 2
                st.rerun()
        if st.button("변경 없이 상품 선택으로 →"):
            state["phase"] = 2
            st.rerun()
        return
    if phase == 2:
        st.caption(f"수량 {r.inputs.quantity}대 · 배송비 포함 예산 {money(r.inputs.budget_krw)}")
        if st.button("← 구매 조건"):
            clear_confirmations(state)
            state["phase"] = 1
            st.rerun()
        candidates_screen(service, context, state, detail)
        if "review" in detail.allowed_actions:
            if st.button(
                "검토하고 문서 만들기 →", disabled=r.selected_evidence_id is None, type="primary"
            ):
                with st.spinner("규정 검토 및 문서 생성 중…"):
                    review = result_data(service.review_request(context, ref_of(r)))
                    if review and result_data(
                        service.generate_documents(
                            context,
                            RequestRef(request_id=review.request_id, version=review.version),
                        )
                    ):
                        clear_confirmations(state)
                        state["phase"] = 3
                        st.rerun()
        elif editable:
            st.info(
                "제출 이후 상품을 바꾸려면 다른 상품을 선택하거나 구매 조건을 수정해 새 버전을 만들어 주세요."
            )
        return
    selected = next((e for e in detail.candidates if e.evidence_id == r.selected_evidence_id), None)
    if selected:
        st.text(f"{selected.product.productName} · {r.inputs.quantity}대")
    total = detail.review.review_total_krw if detail.review else None
    metrics = st.columns(3)
    metrics[0].metric("배송비 포함 총액", money(total))
    metrics[1].metric("구매 예산", money(r.inputs.budget_krw))
    metrics[2].metric(
        "남은 예산", money(r.inputs.budget_krw - total if total is not None else None)
    )
    if detail.review:
        for reason in detail.blocked_reasons:
            st.warning(reason)
        if detail.review.missing_fields:
            fields = dict(purpose="구매 목적", selected_product="선택 상품", shipping="배송비 근거")
            st.warning(
                "보완 항목: " + ", ".join(fields.get(f, f) for f in detail.review.missing_fields)
            )
    if detail.history and r.status in ("needs_revision", "rejected"):
        st.markdown("**담당자 처리 의견**")
        st.text(detail.history[-1].reason or "의견 없음")
    if detail.documents:
        document_tabs(service, context, detail)
    else:
        st.info("문서가 없습니다. 상품 선택 단계에서 문서를 만들어 주세요.")
    with st.container(key="action_footer"):
        if editable:
            back, edit = st.columns(2)
            if back.button("← 상품 선택"):
                clear_confirmations(state)
                state["phase"] = 2
                st.rerun()
            if edit.button(
                "구매 조건 보완" if r.status in ("needs_revision", "draft") else "구매 조건 수정"
            ):
                clear_confirmations(state)
                state["phase"] = 1
                st.rerun()
        action_panel(service, context, state, detail)


def detail_screen(service, context, state):
    latest = result_data(service.get_latest_request(context, state["request_id"]))
    if latest is None:
        return
    title_area = st.container()
    with st.expander("요청 정보 · 이전 버전"):
        st.caption(
            f"{latest.request.request_id} · {latest.request.department_id} / {latest.request.owner_id}"
        )
        version = st.selectbox(
            "조회 버전",
            list(range(latest.request.version, 0, -1)),
            key=f"version_{latest.request.request_id}_{latest.request.version}",
        )
    detail = (
        latest
        if version == latest.request.version
        else result_data(
            service.get_request(
                context, RequestRef(request_id=latest.request.request_id, version=version)
            )
        )
    )
    if detail is None:
        return
    r = detail.request
    editable = "update" in detail.allowed_actions and version == latest.request.version
    phase = state.get("phase", 3 if detail.documents else 2) if editable else 3
    reviewing = any(d in detail.allowed_actions for d in ("approve", "reject", "request_revision"))
    with title_area:
        heading("결재 검토" if reviewing else "구매요청 상세", r.inputs.purpose or "모니터 구매")
        badge(r.status)
        progress(detail)
    if editable and r.status in ("draft", "ready", "needs_revision", "rejected"):
        steps(phase)
    if state.get("search_notice"):
        st.warning(state.pop("search_notice"))
    if version != latest.request.version:
        st.warning("과거 버전입니다. 읽기 전용이며 처리는 최신 버전에서 가능합니다.")
    show_ai = editable and st.toggle("AI 도우미", value=True, key=f"show_ai_{r.request_id}")
    columns = st.columns([7, 3], gap="large") if show_ai else [st.container()]
    with columns[0]:
        detail_body(service, context, state, detail, phase)
    if show_ai:
        with columns[1]:
            chat_panel(service, context, state, detail)


def main(service=None):
    st.set_page_config(page_title="SK-TASK", page_icon="📁", layout="wide")
    service = (
        service
        if service is not None
        else get_service(os.environ.get("PURCHASE_DB_PATH", str(ROOT / "runtime/purchase.sqlite3")))
    )
    style()
    st.sidebar.title("SK-TASK")
    st.sidebar.caption("Task Automation for Supplier Knowledge")
    # Place settings below navigation, but resolve the active actor before rendering actions.
    navigation = st.sidebar.container()
    settings = st.sidebar.expander("시연 설정")
    profile = settings.selectbox(
        "시연 프로필 · 인증 아님",
        list(DEMO_PROFILES),
        format_func=lambda p: PROFILES.get(p, p),
        key="profile",
    )
    previous = st.session_state.get("active_profile")
    sessions = st.session_state.setdefault("actor_sessions", {})
    if previous != profile:
        if previous in sessions:
            deactivate(sessions[previous])
        for key in list(st.session_state):
            if key not in ("profile", "actor_sessions"):
                del st.session_state[key]
        st.session_state["active_profile"] = profile
    state = sessions.setdefault(
        profile,
        dict(
            session_id=uuid4().hex,
            view="home",
            folder="mine" if DEMO_PROFILES[profile][1] == "requester" else "pending",
            page=1,
            create_id=uuid4().hex,
        ),
    )
    context = demo_context(profile, state["session_id"])
    settings.caption(f"{context.department_id} · {ROLES[context.role]}")
    settings.info("로컬 시연 프로필입니다. 실제 로그인 기능이 아닙니다.")
    with navigation:
        st.text(PROFILES.get(profile, profile))
        if st.button("+ 새 구매요청", type="primary", width="stretch"):
            start_new_purchase(state)
        if st.button("내 업무", width="stretch"):
            move(state, "home")
        folders = (
            ["mine", "completed"]
            if context.role == "requester"
            else ["mine", "pending", "completed"]
        )
        for folder in folders:
            if st.button(FOLDERS[folder], key=f"folder_{folder}", width="stretch"):
                state.update(folder=folder, page=1)
                move(state, "list")
    if state.get("notice"):
        st.success(state.pop("notice"))
    if state["view"] == "create":
        create_screen(service, context, state)
    elif state["view"] == "detail":
        detail_screen(service, context, state)
    elif state["view"] == "list":
        list_screen(service, context, state)
    else:
        home_screen(service, context, state)
    show_confirmation(service, context, state)
