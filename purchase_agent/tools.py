"""서버가 관리하는 세션 컨텍스트에 모두 연결된 LLM 도구 8개."""

from langchain_core.tools import tool

from .guardrails.intent import validate_values
from .schemas import DraftInput, RequestInput, RequestPatch, RequestRef, ToolResult


class ToolStop(RuntimeError):
    pass


def build_tools(session):
    # 모델이 전달하는 업무 인자와 서버가 소유한 사용자 권한을 분리한다.
    # 아래 @tool docstring은 모델에 전달되므로 개발자용 설명은 주석으로 둔다.
    service, ctx = session.service, session.context

    def result(value):
        return value.model_dump(mode="json")

    def failure(code):
        return result(ToolResult(ok=False, error_code=code))

    def ref(request_id, version):
        return RequestRef(request_id=request_id, version=version)

    # 1. 조건 저장·상품 선택: 변경이 있으면 service가 새 버전을 만든다.
    @tool
    def upsert_purchase_request(
        quantity: int | None = None,
        budget_krw: int | None = None,
        purpose: str | None = None,
        requirements: list[str] | None = None,
        selected_evidence_id: str | None = None,
        request_id: str | None = None,
        expected_version: int | None = None,
        clear_purpose: bool = False,
        clear_selection: bool = False,
        use_department_budget: bool = False,
    ):
        """모니터 조건을 저장한다. 예산을 알기 전에도 수량/목적 일부를 저장할 수 있으며, 조건이 완성되어야 요청을 생성한다. use_department_budget은 사용자가 팀 예산을 요청한 경우에만 서버의 모의 부서 한도를 적용한다. 목적은 선택 사항이다. 수정 시에는 request_id와 최신 expected_version이 필요하며, 변경하지 않는 필드는 생략한다. 반환된 selected_evidence_id만 선택한다. 가격/사용자/상태는 절대 전달하지 않는다."""
        if session.search_only and (selected_evidence_id is not None or clear_selection):
            return failure("SEARCH_ONLY: selection changes require a separate user request")
        if use_department_budget and not session.department_budget_requested:
            return failure("DEPARTMENT_BUDGET_NOT_REQUESTED")
        values = {
            key: value
            for key, value in {
                "quantity": quantity,
                "budget_krw": budget_krw,
                "purpose": purpose,
                "requirements": requirements,
                "selected_evidence_id": selected_evidence_id,
            }.items()
            if value is not None
        }
        known = {**session.draft_inputs, **session.confirmed_inputs}
        selected = None
        if session.current_request:
            current = service.get_latest_request(ctx, session.current_request)
            if current.ok:
                known = current.data.request.inputs.model_dump()
                selected = current.data.request.selected_evidence_id
        if (
            not known.get("budget_krw")
            and session.department_budget_requested
            and session.department_budget
        ):
            known = {**known, "budget_krw": session.department_budget["available_krw"]}
        error = validate_values(session, values, known)
        if error:
            return failure(error)
        if (
            selected_evidence_id is not None
            and selected_evidence_id != selected
            and not session.selection_requested
        ):
            return failure(
                "SELECTION_NOT_REQUESTED: 상품 후보를 보여주고 사용자에게 선택을 요청하세요."
            )
        if clear_purpose:
            values["purpose"] = None
        if clear_selection:
            values["selected_evidence_id"] = None
        try:
            if use_department_budget:
                budget = service.get_department_budget(ctx)
                if not budget.ok:
                    return result(budget)
                session.department_budget = budget.data
                if budget_krw is None:
                    values["budget_krw"] = budget.data["available_krw"]
            if request_id is None:
                draft = DraftInput.model_validate(
                    {
                        **session.draft_inputs,
                        **{k: v for k, v in values.items() if k != "selected_evidence_id"},
                    }
                )
                session.draft_inputs = draft.model_dump(exclude_none=True)
                missing = [k for k in ("quantity", "budget_krw") if getattr(draft, k) is None]
                if missing:
                    return result(
                        ToolResult(
                            ok=True,
                            data={
                                "draft": session.draft_inputs,
                                "missing_fields": missing,
                                "persisted": False,
                            },
                        )
                    )
                values = session.draft_inputs
                value = service.create_request(
                    ctx, RequestInput.model_validate(values), session.action_id
                )
                if value.ok:
                    created = value.data
                    session.current_request = created.request_id
                    if session.explored:
                        found = service.search_products(
                            ctx,
                            ref(created.request_id, created.version),
                            session.explored[0].query,
                            10,
                            sort_by=session.exploration_sort,
                        )
                        if not found.ok:
                            return result(found)
                    if selected_evidence_id is not None:
                        value = service.update_request(
                            ctx,
                            created.request_id,
                            RequestPatch(
                                expected_version=created.version,
                                selected_evidence_id=selected_evidence_id,
                            ),
                        )
            else:
                value = service.update_request(
                    ctx,
                    request_id,
                    RequestPatch.model_validate({**values, "expected_version": expected_version}),
                )
            if value.ok:
                session.current_request = value.data.request_id
                if selected_evidence_id is not None:
                    session.selection_requested = False
                    session.selection_instruction = None
            elif value.error_code == "UNKNOWN_PRODUCT" and request_id:
                latest = service.get_latest_request(ctx, request_id)
                if latest.ok:
                    return failure(
                        "UNKNOWN_PRODUCT: use selected_evidence_id exactly from "
                        + str([e.evidence_id for e in latest.data.candidates])
                    )
            return result(value)
        except ValueError:
            return failure(
                "INVALID_INPUT: quantity 1-20, budget_krw positive integer; update needs expected_version"
            )

    # 2. 검색: 이후 선택에는 응답의 selected_evidence_id와 최신 version을 사용한다.
    @tool
    def search_coupang_products(
        keyword: str,
        request_id: str | None = None,
        version: int | None = None,
        limit: int = 10,
        refresh: bool = False,
        sort_by: str = "relevance",
    ):
        """요청이 생성되기 전에도 모의 Coupang 데이터를 검색한다. 높은 가격 우선이면 price_desc, 낮은 가격 우선이면 price_asc를 사용하며, limit 적용 전에 정렬한다. request_id가 없으면 후보만 탐색하며 구매요청을 생성하지 않는다. 카탈로그를 사용할 수 없을 수 있으므로 상품을 지어내지 않는다. 새로고침으로 요청의 새 버전이 생성될 수 있으므로 이후 get_request_status를 호출한다."""
        # 이 실습은 모니터 전용 스냅샷을 검색한다. 자연어 설명은
        # '업무용 모니터'처럼 해당 카테고리를 사용하며, 필수 사양은 정책 입력으로 유지한다.
        query = "모니터" if "모니터" in keyword else keyword
        if request_id is None:
            value = service.explore_products(ctx, query, limit, sort_by)
            if not value.ok:
                raise ToolStop(value.error_code)
            session.explored = value.data
            session.exploration_sort = sort_by
            session.search_completed = True
            return result(
                ToolResult(
                    ok=True,
                    data={
                        "candidates": value.data,
                        "persisted": False,
                        "scope": "등록된 모의 카탈로그의 검색 후보",
                        "draft": session.draft_inputs,
                    },
                )
            )
        if version is None:
            return failure("VERSION_REQUIRED")
        value = service.search_products(
            ctx, ref(request_id, version), query, limit, refresh, sort_by
        )
        if not value.ok:
            raise ToolStop(value.error_code)
        latest = service.get_latest_request(ctx, request_id)
        session.search_completed = True
        preferences = service.get_preferences(ctx)
        from .preferences import order_candidates

        value.data = order_candidates(
            value.data, preferences.data if preferences.ok else {}, latest.data.request.inputs
        )
        if not value.data:
            raise ToolStop("EMPTY_CANDIDATES")
        return result(
            ToolResult(
                ok=True,
                data={
                    "candidates": value.data,
                    "selection_keys": [
                        {
                            "selected_evidence_id": e.evidence_id,
                            "productName": e.product.productName,
                        }
                        for e in value.data
                    ],
                    "request_id": request_id,
                    "version": latest.data.request.version,
                },
            )
        )

    # 3. 검토: 금액·배송비·규정 판정은 모델 대신 업무 코드가 계산한다.
    @tool
    def review_purchase_request(request_id: str, version: int):
        """저장된 근거로 배송비를 포함한 총액을 계산하고 정책을 검사한다. 목적/배송 정보가 없으면 제출은 차단하지만 초안은 허용한다."""
        if session.search_only:
            return failure("SEARCH_ONLY")
        return result(service.review_request(ctx, ref(request_id, version)))

    # 4. 문서: 같은 요청 버전과 검토 결과로 문서 3종을 함께 생성한다.
    @tool
    def generate_documents(request_id: str, version: int):
        """해당 버전의 검토 결과로 Markdown 문서 3종을 생성한다. 먼저 review를 호출하며, 금액이나 목적을 지어내지 않는다."""
        if session.search_only:
            return failure("SEARCH_ONLY")
        value = service.generate_documents(ctx, ref(request_id, version))
        if value.ok:
            session.document_generated = True
        return result(value)

    # 5. 제출: HITL 중단을 재개한 뒤 서버 발급 확인 토큰이 있어야 실행된다.
    @tool
    def submit_purchase_request(request_id: str, version: int, bundle_id: str):
        """준비가 완료된 기존 문서 묶음의 내부 제출을 제안한다. 반드시 실행을 중단하고 UI에서 사용자의 명시적 확인을 받아야 하며, 구매나 결제는 절대 하지 않는다."""
        if not session.submission_requested:
            return failure("SUBMISSION_NOT_REQUESTED")
        confirmation = session.confirmation
        if not confirmation or (
            confirmation.request_id,
            confirmation.version,
            confirmation.bundle_id,
        ) != (request_id, version, bundle_id):
            return failure("CONFIRMATION_REQUIRED")
        value = service.submit_request(ctx, confirmation)
        session.confirmation = None
        return result(value)

    @tool
    def get_request_status(request_id: str):
        """접근 권한이 있는 최신 요청, 버전, 근거, 문서와 승인 이력을 조회한다."""
        value = service.get_latest_request(ctx, request_id)
        if value.ok:
            session.current_request = request_id
        return result(value)

    @tool
    def get_department_budget():
        """호출자 소속 부서의 모의 잔액과 요청당 한도만 조회한다. 다른 부서의 예산을 추측하지 않는다. 이는 실시간 회계 정보가 아닌 실습용 고정 스냅샷이다. 사용자가 팀 예산을 요청했을 때 적용하려면 use_department_budget=true로 upsert를 사용한다."""
        value = service.get_department_budget(ctx)
        if value.ok:
            session.department_budget = value.data
        return result(value)

    @tool
    def save_user_preferences(comparison_priority: str = "price", output_style: str = "concise"):
        """이번 UI 이벤트에서 사용자가 동의에 체크한 경우에만 민감하지 않은 선호를 저장한다. priority 허용값: price/specification; style 허용값: concise/detailed."""
        return result(
            service.save_preferences(
                ctx,
                {"comparison_priority": comparison_priority, "output_style": output_style},
                consent=session.preference_consent,
            )
        )

    return [
        upsert_purchase_request,
        search_coupang_products,
        review_purchase_request,
        generate_documents,
        submit_purchase_request,
        get_request_status,
        save_user_preferences,
        get_department_budget,
    ]
