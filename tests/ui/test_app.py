from datetime import datetime, timezone
from streamlit.testing.v1 import AppTest
from purchase_agent.config import demo_context
from purchase_agent.schemas import RequestInput, RequestPatch, ProductEvidence, CoupangProduct, ProductSupplement
from purchase_agent.workflow import LocalPurchaseService


def run_app(service):
    from unittest.mock import patch
    at = AppTest.from_string('from purchase_agent.ui.app import main\nmain()')
    with patch('purchase_agent.ui.app.get_service', return_value=service):
        at.run(timeout=15)
    at._test_service = service
    return at


def rerun(at):
    from unittest.mock import patch
    with patch('purchase_agent.ui.app.get_service', return_value=at._test_service):
        at.run(timeout=15)
    assert not at.exception
    return at


def click(at, label):
    next(b for b in at.button if b.label == label).click()
    return rerun(at)


def seed(service, purpose='업무', quantity=1):
    owner = demo_context('employee_a', 'seed')
    r = service.create_request(owner, RequestInput(quantity=quantity,budget_krw=2000000,purpose=purpose), 'seed').data
    service.search_products(owner,r,'monitor')
    r = service.update_request(owner,r.request_id,RequestPatch(expected_version=r.version,selected_evidence_id='e1')).data
    service.review_request(owner,r)
    service.generate_documents(owner,r)
    return r, owner


def service_with_products(tmp_path):
    now = datetime.now(timezone.utc)
    catalog = [ProductEvidence(evidence_id=f'e{i}', product=CoupangProduct(productId=i,productName=f'Synthetic monitor {i}',productPrice=280000, productUrl=f'https://www.coupang.com/vp/products/{i}',productImage='https://example.com/test.png',isRocket=False,isFreeShipping=True,keyword='monitor',rank=i), supplement=ProductSupplement(product_id=i,item_id=str(i),vendor_item_id=str(i),option_label='QHD',verified_specs=['QHD'],shipping_rule='free',shipping_source_url=f'https://www.coupang.com/vp/products/{i}',source_checked_at=now,source_status='verified'),query='monitor',retrieved_at=now,fixture_version='test') for i in (1,2)]
    return LocalPurchaseService(tmp_path/'ui.db',catalog)


def test_create_empty_catalog_and_role_isolation(tmp_path):
    service = LocalPurchaseService(tmp_path/'empty.db')
    at = run_app(service)
    assert not at.exception
    click(at, '구매요청 작성')
    click(at, '저장하고 상품 찾기')
    assert any('조건은 저장했지만' in w.value for w in at.warning)
    click(at, '후보 검색')
    assert any('실제 상품 자료가 없습니다' in e.value for e in at.error)
    actor_thread = at.session_state['actor_sessions']['employee_a']['session_id']
    at.selectbox(key='profile').select('employee_b')
    rerun(at)
    assert any('처리할 구매요청이 없습니다' in i.value for i in at.info)
    at.selectbox(key='profile').select('employee_a')
    rerun(at)
    assert at.session_state['actor_sessions']['employee_a']['session_id'] == actor_thread


def test_missing_purpose_document_tabs_and_disabled_submit(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service, purpose=None)
    at = run_app(service)
    click(at, '열기')
    assert [t.label for t in at.tabs] == ['구매요청서','상품 비교표','규정 검토']
    assert next(b for b in at.button if b.label == '구매요청 제출 확인').disabled
    assert len(at.get('download_button')) == 3
    assert any('구매 목적' in w.value for w in at.warning)
    assert service.get_request(owner,r).data.request.submitted_at is None


def test_explicit_confirmation_cancel_role_change_and_high_approval(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service, quantity=4)
    at = run_app(service)
    click(at,'열기')
    click(at,'구매요청 제출 확인')
    confirmation = at.session_state['actor_sessions']['employee_a']['confirmation']
    assert confirmation.token not in '\n'.join(t.value for t in at.text)
    click(at,'취소')
    assert service.get_request(owner,r).data.request.status == 'ready'
    click(at,'구매요청 제출 확인')
    at.selectbox(key='profile').select('employee_b')
    rerun(at)
    at.selectbox(key='profile').select('employee_a')
    rerun(at)
    assert at.session_state['actor_sessions']['employee_a']['confirmation'] is None
    click(at,'구매요청 제출 확인')
    click(at,'제출')
    assert len(service.get_request(owner,r).data.history) == 1
    at.selectbox(key='profile').select('buyer_a')
    rerun(at)
    click(at,'열기')
    next(s for s in at.selectbox if s.label == '처리 종류').select('reject')
    rerun(at)
    assert next(b for b in at.button if b.label == '처리 내용 확인').disabled
    next(s for s in at.selectbox if s.label == '처리 종류').select('approve')
    rerun(at)
    click(at,'처리 내용 확인')
    click(at,'확인하여 처리')
    assert service.get_request(owner,r).data.request.status == 'additional_approval'
    at.selectbox(key='profile').select('manager_a')
    rerun(at)
    click(at,'열기')
    click(at,'처리 내용 확인')
    click(at,'확인하여 처리')
    assert service.get_request(owner,r).data.request.status == 'approved'


def test_edit_and_search_refresh_use_latest_version(tmp_path):
    service = service_with_products(tmp_path)
    r, owner = seed(service)
    at = run_app(service)
    click(at, '열기')
    click(at, '구매 조건 보완')
    next(t for t in at.text_area if t.label.startswith('구매 목적')).input('새 업무 목적')
    click(at, '구매 조건 저장')
    latest = service.get_latest_request(owner,r.request_id).data
    assert latest.request.version == r.version + 1
    assert latest.documents is None
    service.catalog[0].product.productPrice += 1000
    next(t for t in at.text_input if t.label == '상품 검색어').input('monitor')
    next(c for c in at.checkbox if c.label == '상품 근거 새로 조회').check()
    click(at, '후보 검색')
    latest = service.get_latest_request(owner,r.request_id).data
    assert latest.request.version == r.version + 2
    assert next(s for s in at.selectbox if s.label == '조회 버전').value == latest.request.version
    click(at, '문서 만들기 →')
    assert service.get_latest_request(owner,r.request_id).data.review.version == latest.request.version
    next(s for s in at.selectbox if s.label == '조회 버전').select(r.version)
    rerun(at)
    assert any('읽기 전용' in w.value for w in at.warning)
    assert not any(b.label == '문서 만들기 →' for b in at.button)


def test_create_searches_and_shows_next_step(tmp_path):
    service = service_with_products(tmp_path)
    for evidence in service.catalog:
        evidence.query = '모니터'
    at = run_app(service)
    click(at, '구매요청 작성')
    assert any('① 구매 조건 · 현재 단계' in i.value for i in at.info)
    click(at, '저장하고 상품 찾기')
    assert any('② 상품 비교·선택 · 현재 단계' in i.value for i in at.info)
    assert any(s.label == '구매 상품 선택' for s in at.selectbox)
    assert not at.tabs
    assert not any(t.label.startswith('구매 목적') for t in at.text_area)
    state = at.session_state['actor_sessions']['employee_a']
    detail = service.get_latest_request(demo_context('employee_a', state['session_id']), state['request_id']).data
    assert len(detail.candidates) == 2
    assert detail.request.selected_evidence_id is None
    assert detail.request.submitted_at is None
    next(s for s in at.selectbox if s.label == '구매 상품 선택').select('e1')
    rerun(at)
    click(at, '선택 상품 적용')
    click(at, '문서 만들기 →')
    assert any('③ 문서 확인·제출 · 현재 단계' in i.value for i in at.info)
    assert not any(s.label == '구매 상품 선택' for s in at.selectbox)
    click(at, '← 상품 선택')
    assert any(s.label == '구매 상품 선택' for s in at.selectbox)
    assert not at.tabs

def test_price_preference_orders_visible_candidates(tmp_path):
    service=service_with_products(tmp_path)
    service.catalog[1].product.productPrice=200000
    ref,owner=seed(service)
    service.save_preferences(owner,{'comparison_priority':'price'},consent=True)
    at=run_app(service);click(at,'열기');click(at,'← 상품 선택')
    selector=next(s for s in at.selectbox if s.label=='구매 상품 선택')
    assert selector.options[0].startswith('Synthetic monitor 2')
