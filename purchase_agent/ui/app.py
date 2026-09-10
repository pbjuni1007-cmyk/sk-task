"""Local purchase screens. The optional AI integration must be supplied separately."""
from datetime import datetime, time, timezone
from pathlib import Path
from uuid import uuid4
import os
import streamlit as st
from purchase_agent.catalog import load_catalog
from purchase_agent.config import DEMO_PROFILES, demo_context
from purchase_agent.policy import shipping_total
from purchase_agent.schemas import RequestInput, RequestPatch, RequestRef, ListQuery, DecisionInput
from purchase_agent.workflow import LocalPurchaseService
from purchase_agent.ui.chat import panel as chat_panel

ROOT = Path(__file__).resolve().parents[2]
STATUS = dict(draft='작성중 · 보완 필요', ready='제출 가능', submitted='구매팀 검토중',
              additional_approval='추가 결재 대기', approved='승인 완료', rejected='반려', needs_revision='보완 요청')
FOLDERS = dict(mine='내 요청함', pending='결재대기함', revision='보완요청함', completed='완료 문서함')
ROLES = dict(requester='요청 직원', buyer='구매 담당자', manager='추가 승인자')
DOCS = dict(purchase_request='구매요청서', comparison='상품 비교표', review='규정 검토')
ERRORS = {
    'CATALOG_NOT_VERIFIED': '확인된 실제 상품 자료가 없습니다. 상품·옵션·판매자·배송 근거를 준비한 뒤 다시 검색해 주세요.',
    'STALE_VERSION': '다른 작업에서 새 버전이 만들어졌습니다. 최신 요청을 다시 열어 주세요.',
    'NOT_READY': '제출 조건이 충족되지 않았습니다. 누락 항목을 보완하고 문서를 다시 검토해 주세요.',
    'FORBIDDEN': '이 요청에 접근할 권한이 없습니다. 내 요청함으로 돌아가 주세요.',
    'CONFIRMATION_EXPIRED': '제출 확인이 만료되었습니다. 최신 문서에서 제출 확인을 다시 열어 주세요.',
    'STORAGE_ERROR': '저장소 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.',
}

@st.cache_resource
def get_service(path):
    """One service boot identity across reruns and sessions for this DB path."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return LocalPurchaseService(path, catalog=load_catalog(ROOT / 'fixtures/coupang'))


def money(value):
    return '확인 필요' if value is None else f'{value:,}원'


def result_data(result):
    if not result.ok:
        st.error(ERRORS.get(result.error_code, '처리할 수 없습니다. 입력·권한·최신 버전을 확인한 뒤 다시 시도해 주세요.'))
        return None
    return result.data


def ref_of(request):
    return RequestRef(request_id=request.request_id, version=request.version)


def move(state, view, request_id=None):
    state.update(view=view, request_id=request_id, confirmation=None, decision=None)
    state.pop('phase', None)
    st.rerun()


def inputs_form(inputs, key, submit_label='구매 조건 저장'):
    with st.form(key):
        a, b = st.columns(2)
        quantity = a.number_input('수량', min_value=1, max_value=20, value=inputs.quantity)
        budget = b.number_input('예산 · 배송비 포함 (원)', min_value=1, value=inputs.budget_krw, step=10000)
        requirements = st.text_area('희망 사양 · 한 줄에 하나', value='\n'.join(inputs.requirements), placeholder='예: 27인치\nFHD\nUSB-C 연결')
        purpose = st.text_area('구매 목적 · 제출 전 필수', value=inputs.purpose or '', max_chars=500, placeholder='예: 신규 입사자 3명의 업무용 모니터 지급')
        saved = st.form_submit_button(submit_label, type='primary')
    if saved:
        return RequestInput(quantity=quantity, budget_krw=budget,
                            requirements=[s.strip() for s in requirements.splitlines() if s.strip()], purpose=purpose)
    return None


def flow_steps(current):
    labels = ['① 구매 조건', '② 상품 비교·선택', '③ 문서 확인·제출']
    for index, (column, label) in enumerate(zip(st.columns(3), labels), 1):
        with column:
            if index == current:
                st.info(f'{label} · 현재 단계')
            else:
                st.caption(label)


def create_screen(service, context, state):
    st.header('구매요청 작성')
    flow_steps(1)
    st.write('문장으로 입력하거나 아래 양식을 채워주세요.')
    entry = st.radio('입력 방법', ['직접 입력', 'AI로 입력'], horizontal=True)
    if entry == 'AI로 입력':
        chat_panel(service, context, state)
        return
    st.subheader('① 구매 조건 직접 입력')
    st.caption('저장하면 등록된 모니터 후보를 바로 검색합니다. 구매 목적은 제출 전까지 입력하면 됩니다.')
    values = inputs_form(RequestInput(quantity=1, budget_krw=300000), 'create', '저장하고 상품 찾기')
    if values:
        request = result_data(service.create_request(context, values, state['create_id']))
        if request:
            state['create_id'] = uuid4().hex
            with st.spinner('조건을 저장하고 상품을 찾는 중…'):
                found = service.search_products(context, ref_of(request), '모니터')
            if found.ok and found.data:
                state['notice'] = '조건을 저장했습니다. 아래 후보를 비교하고 구매할 상품을 선택하세요.'
            else:
                state['search_notice'] = ('조건은 저장했지만 검색에 실패했습니다. 아래 후보 검색에서 다시 시도해 주세요.'
                                          if not found.ok else '조건은 저장했지만 후보가 없습니다. 검색 조건을 바꿔 주세요.')
            move(state, 'detail', request.request_id)


def list_screen(service, context, state):
    st.header(FOLDERS[state['folder']])
    with st.form('filters'):
        cols = st.columns(4)
        keyword = cols[0].text_input('요청번호 또는 제목')
        department = cols[1].selectbox('부서', ['', *sorted({v[0] for v in DEMO_PROFILES.values()})], format_func=lambda x: x or '전체 부서')
        start = cols[2].date_input('제출일 시작', value=None)
        end = cols[3].date_input('제출일 종료', value=None)
        if st.form_submit_button('조회'):
            state['page'] = 1
    if start and end and start > end:
        st.error('시작일은 종료일보다 늦을 수 없습니다.')
        return
    query = ListQuery(folder=state['folder'], keyword=keyword, department_id=department or None,
                      date_from=datetime.combine(start,time.min,tzinfo=timezone.utc) if start else None,
                      date_to=datetime.combine(end,time.max,tzinfo=timezone.utc) if end else None,
                      page=state['page'], page_size=10)
    page = result_data(service.list_requests(context, query))
    if page is None:
        return
    st.caption(f'총 {page.total}건 · {state["page"]}페이지')
    if not page.items:
        st.info('처리할 구매요청이 없습니다. 검색 조건이 있다면 비우고 다시 조회해 주세요.')
    for detail in page.items:
        r = detail.request
        with st.container(border=True):
            row = st.columns([4, 2, 2, 1])
            row[0].text(r.inputs.purpose or '목적 미입력 · 모니터 구매')
            row[0].caption(f'{r.request_id} · 버전 {r.version}')
            row[1].text(f'{r.department_id} / {r.owner_id}')
            row[1].caption(r.submitted_at.isoformat(timespec='minutes') if r.submitted_at else '제출일 —')
            row[2].text(money(detail.review.review_total_krw if detail.review else None))
            row[2].caption(STATUS[r.status])
            if row[3].button('열기', key=f'open_{r.request_id}'):
                move(state, 'detail', r.request_id)
    a, b = st.columns(2)
    if a.button('이전 페이지', disabled=state['page'] <= 1):
        state['page'] -= 1
        st.rerun()
    if b.button('다음 페이지', disabled=state['page'] * 10 >= page.total):
        state['page'] += 1
        st.rerun()


def candidates_screen(service, context, state, detail):
    from purchase_agent.preferences import order_candidates
    preferences = service.get_preferences(context)
    detail = detail.model_copy(update={'candidates': order_candidates(detail.candidates, preferences.data if preferences.ok else {}, detail.request.inputs)})
    r = detail.request
    if 'search' in detail.allowed_actions:
        with st.expander('검색 조건 변경 · 다시 검색', expanded=not bool(detail.candidates)), st.form(f'search_{r.version}'):
            keyword = st.text_input('상품 검색어', value='모니터')
            refresh = st.checkbox('상품 근거 새로 조회')
            search = st.form_submit_button('후보 검색')
        if search:
            if not keyword.strip():
                st.error('검색어를 입력해 주세요.')
            else:
                with st.spinner('후보 검색 중…'):
                    found = result_data(service.search_products(context, ref_of(r), keyword, refresh=refresh))
                if found is not None:
                    # Search may have created a version; never reuse the displayed ref.
                    latest = result_data(service.get_latest_request(context, r.request_id))
                    if latest:
                        state['confirmation'] = None
                        state['notice'] = '검색 결과가 없습니다. 검색 조건을 바꿔 주세요.' if not found else '후보를 검색했습니다.'
                        st.rerun()
    if not detail.candidates:
        st.info('후보가 없습니다. 확인된 상품 자료를 검색한 뒤 선택해 주세요.')
        return
    rows = []
    for e in detail.candidates:
        fee = shipping_total(e.supplement, r.inputs.quantity)
        total = None if fee is None else e.product.productPrice * r.inputs.quantity + fee
        rows.append({'상품': e.product.productName, '옵션': e.supplement.option_label or '확인 필요',
                     '단가': money(e.product.productPrice),
                     '수량별 배송비': money(fee), '총액': money(total),
                     '예산': '확인 필요' if total is None else ('이내' if total <= r.inputs.budget_krw else '초과'),
                     '상품 링크': str(e.product.productUrl)})
    with st.expander('상품 정보 출처'):
        st.caption('사용자 확인 자료를 사용하는 모의 검색입니다. 가격과 배송 조건은 실시간 정보가 아닙니다.')
        for e in detail.candidates:
            st.text(f'{e.product.productName} · 확인 기록 {e.supplement.source_checked_at}')
    import json
    source_path = ROOT / 'fixtures/coupang/user-provided-products.json'
    sellers = {}
    if source_path.exists():
        sellers = {r['productId']: r['seller'] for r in json.loads(source_path.read_text())['products']}
    for e, row in zip(detail.candidates, rows):
        with st.container(border=True):
            picture, info = st.columns([1, 4])
            picture.image(str(e.product.productImage), width=130)
            info.write(e.product.productName)
            info.caption(f"{row['옵션']} · 판매자 {sellers.get(e.product.productId, '확인 필요')}")
            info.write(f"단가 {row['단가']} · 배송비 {row['수량별 배송비']}")
            info.write(f"**총액 {row['총액']} · 예산 {row['예산']}**")
            info.link_button('쿠팡 상품 보기', str(e.product.productUrl))
    if 'update' in detail.allowed_actions:
        evidence = {e.evidence_id: e for e in detail.candidates}
        ids = list(evidence)
        selected = st.selectbox('구매 상품 선택', ids, index=ids.index(r.selected_evidence_id) if r.selected_evidence_id in ids else None,
                                format_func=lambda k: f'{evidence[k].product.productName} · {evidence[k].supplement.option_label or "옵션 확인 필요"}', key=f'candidate_{r.version}')
        if st.button('선택 상품 적용', disabled=selected is None):
            updated = result_data(service.update_request(context, r.request_id, RequestPatch(expected_version=r.version, selected_evidence_id=selected)))
            if updated:
                state['confirmation'] = None
                st.rerun()


def document_tabs(service, context, detail):
    r = detail.request
    show_history = bool(detail.history or r.submitted_at)
    tabs = st.tabs([*DOCS.values(), *(['결재 이력'] if show_history else [])])
    for tab, (kind, label) in zip(tabs, DOCS.items()):
        with tab:
            if detail.documents and kind in detail.documents.files:
                # Plain text keeps both product text and generated Markdown inert.
                st.text(detail.documents.files[kind])
                data = result_data(service.download_document(context, ref_of(r), kind))
                if data is not None:
                    st.download_button(f'{label} 다운로드', data, file_name=f'{r.request_id}_v{r.version}_{kind}.md', mime='text/markdown')
            else:
                st.info('문서 초안이 아직 없습니다.')
            if kind == 'review' and detail.review:
                with st.expander('규정 검토 상세'):
                    st.dataframe([c.model_dump() for c in detail.review.checks], hide_index=True, width='stretch')
    if show_history:
        with tabs[3]:
            if not detail.history:
                st.info('이 버전의 결재 이력이 없습니다.')
            for event in detail.history:
                st.text(f'{event.created_at.isoformat(timespec="minutes")} · {event.actor_id} · {event.decision} · {event.reason or "—"}')


def action_panel(service, context, state, detail):
    r = detail.request
    can_submit = 'submit' in detail.allowed_actions and bool(detail.review and detail.review.can_submit and detail.documents and detail.documents.complete)
    if r.owner_id == context.actor_id and 'update' in detail.allowed_actions:
        if st.button('구매요청 제출 확인', disabled=not can_submit, type='primary'):
            confirmation = result_data(service.prepare_submission(context, ref_of(r), detail.documents.bundle_id))
            if confirmation:
                state['confirmation'] = confirmation
        confirmation = state.get('confirmation')
        if confirmation and (confirmation.version != r.version or not detail.documents or confirmation.bundle_id != detail.documents.bundle_id or not can_submit):
            state['confirmation'] = None
            confirmation = None
        if confirmation:
            with st.container(border=True):
                st.subheader('구매요청 제출 확인')
                selected = next(e for e in detail.candidates if e.evidence_id == r.selected_evidence_id)
                st.text(f'{r.request_id} · 버전 {r.version}\n{selected.product.productName} · {r.inputs.quantity}대\n배송비 포함 {money(detail.review.review_total_krw)}')
                st.text('결재 경로: ' + ' → '.join(ROLES[a] for a in detail.review.required_approvers))
                st.caption(f'검토 문서: 버전 {detail.documents.version}의 구매요청서 · 상품 비교표 · 규정 검토')
                a, b = st.columns(2)
                if a.button('취소', key='cancel_submit'):
                    state['confirmation'] = None
                    st.rerun()
                if b.button('제출', type='primary', key='confirm_submit'):
                    submitted = result_data(service.submit_request(context, confirmation))
                    if submitted:
                        state['confirmation'] = None
                        state['notice'] = f'제출 완료 · 최초 제출 시각 {submitted.submitted_at.isoformat(timespec="seconds")}'
                        st.rerun()
    decisions = [d for d in ('approve', 'reject', 'request_revision') if d in detail.allowed_actions]
    if decisions:
        st.subheader('담당자 처리')
        names = dict(approve='승인', reject='반려', request_revision='보완 요청')
        decision = st.selectbox('처리 종류', decisions, format_func=names.get)
        reason = st.text_area('처리 의견 · 반려 / 보완 요청 시 필수')
        if st.button('처리 내용 확인', disabled=decision != 'approve' and not reason.strip()):
            state['decision'] = DecisionInput(request_id=r.request_id, version=r.version, decision=decision, reason=reason.strip() or None)
        pending = state.get('decision')
        if pending and pending.version == r.version:
            st.text(f'{names[pending.decision]} 확인 · {pending.reason or "의견 없음"}')
            a, b = st.columns(2)
            if a.button('처리 취소'):
                state['decision'] = None
                st.rerun()
            if b.button('확인하여 처리', type='primary'):
                updated = result_data(service.decide(context, pending))
                if updated:
                    state['decision'] = None
                    state['notice'] = STATUS[updated.status]
                    st.rerun()


def detail_screen(service, context, state):
    latest = result_data(service.get_latest_request(context, state['request_id']))
    if latest is None:
        return
    with st.expander('요청 정보 · 이전 버전'):
        st.caption(f'{latest.request.request_id} · {latest.request.department_id} / {latest.request.owner_id}')
        version = st.selectbox('조회 버전', list(range(latest.request.version, 0, -1)), key=f'version_{latest.request.request_id}_{latest.request.version}')
    detail = latest if version == latest.request.version else result_data(service.get_request(context, RequestRef(request_id=latest.request.request_id, version=version)))
    if detail is None:
        return
    r = detail.request
    editable = 'update' in detail.allowed_actions
    phase = state.get('phase', 3 if detail.documents else 2)
    if not editable or version != latest.request.version:
        phase = 3
    st.header({1: '구매 조건', 2: '상품 비교·선택', 3: '문서 확인·제출'}[phase])
    flow_steps(phase)
    if state.get('search_notice'):
        st.warning(state.pop('search_notice'))
    if version != latest.request.version:
        st.warning('과거 버전입니다. 읽기 전용이며 처리는 최신 버전에서 가능합니다.')
    if phase == 1:
        values = inputs_form(r.inputs, f'edit_{r.request_id}_{r.version}')
        if values:
            updated = result_data(service.update_request(context, r.request_id, RequestPatch(expected_version=r.version, **values.model_dump(exclude={'item_type'}))))
            if updated:
                state.update(phase=2, confirmation=None)
                st.rerun()
        if st.button('변경 없이 상품 선택으로 →'):
            state['phase'] = 2
            st.rerun()
        return
    if phase == 2:
        st.caption(f'수량 {r.inputs.quantity}대 · 배송비 포함 예산 {money(r.inputs.budget_krw)}')
        if st.button('← 구매 조건'):
            state.update(phase=1, confirmation=None)
            st.rerun()
        candidates_screen(service, context, state, detail)
        if 'review' in detail.allowed_actions:
            if st.button('문서 만들기 →', disabled=r.selected_evidence_id is None, type='primary'):
                with st.spinner('규정 검토 및 문서 생성 중…'):
                    review = result_data(service.review_request(context, ref_of(r)))
                    if review and result_data(service.generate_documents(context, RequestRef(request_id=review.request_id, version=review.version))):
                        state.update(phase=3, confirmation=None)
                        st.rerun()
        return
    st.caption(STATUS[r.status])
    if r.submitted_at and r.owner_id == context.actor_id:
        st.success('제출된 요청입니다. 처리 상태는 내 요청함에서 확인할 수 있습니다.')
        if st.button('내 요청함으로 돌아가기'):
            state['folder'] = 'mine'
            move(state, 'list')
    if editable:
        back, edit = st.columns(2)
        if back.button('← 상품 선택'):
            state.update(phase=2, confirmation=None)
            st.rerun()
        if edit.button('구매 조건 보완'):
            state.update(phase=1, confirmation=None)
            st.rerun()
    selected = next((e for e in detail.candidates if e.evidence_id == r.selected_evidence_id), None)
    if selected:
        st.write(f'{selected.product.productName} · {r.inputs.quantity}대')
    if detail.review:
        st.metric('배송비 포함 총액', money(detail.review.review_total_krw))
        if detail.review.missing_fields:
            fields = dict(purpose='구매 목적', selected_product='선택 상품', shipping='배송비 근거')
            st.warning('보완 항목: ' + ', '.join(fields.get(f, f) for f in detail.review.missing_fields))
        for reason in detail.blocked_reasons:
            st.warning(reason)
    if detail.documents:
        document_tabs(service, context, detail)
    else:
        st.info('문서가 없습니다. 상품 선택 단계에서 문서를 만들어 주세요.')
    action_panel(service, context, state, detail)


def main(service=None):
    st.set_page_config(page_title='SK-TASK', page_icon='📁', layout='wide')
    service = service if service is not None else get_service(os.environ.get('PURCHASE_DB_PATH', str(ROOT / 'runtime/purchase.sqlite3')))
    st.title('SK-TASK')
    st.caption('Task Automation for Supplier Knowledge')
    settings = st.sidebar.expander('시연 설정')
    profile = settings.selectbox('시연 프로필 · 인증 아님', list(DEMO_PROFILES), key='profile')
    if st.session_state.get('active_profile') != profile:
        # Widget state and pending confirmation must never follow a role change.
        for key in list(st.session_state):
            if key not in ('profile', 'actor_sessions'):
                del st.session_state[key]
        st.session_state['active_profile'] = profile
    sessions = st.session_state.setdefault('actor_sessions', {})
    state = sessions.setdefault(profile, dict(session_id=uuid4().hex, view='list', folder='mine' if DEMO_PROFILES[profile][1] == 'requester' else 'pending', page=1, create_id=uuid4().hex))
    if state.get('last_active') is False:
        state.update(confirmation=None, decision=None)
        state.pop('agent',None)
        state.pop('agent_result',None)
    for actor, actor_state in sessions.items():
        actor_state['last_active'] = actor == profile
    context = demo_context(profile, state['session_id'])
    settings.caption(f'{context.department_id} · {ROLES[context.role]}')
    settings.info('로컬 시연 프로필입니다. 실제 로그인 기능이 아닙니다.')
    if st.sidebar.button('구매요청 작성', type='primary'):
        move(state, 'create')
    folders = ['mine', 'revision', 'completed'] if context.role == 'requester' else list(FOLDERS)
    for folder in folders:
        if st.sidebar.button(FOLDERS[folder], key=f'folder_{folder}'):
            state.update(folder=folder, page=1)
            move(state, 'list')
    if state.get('notice'):
        st.success(state.pop('notice'))
    if state['view'] == 'create':
        create_screen(service, context, state)
    elif state['view'] == 'detail':
        detail_screen(service, context, state)
    else:
        list_screen(service, context, state)
