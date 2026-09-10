import pytest
from pydantic import ValidationError
from purchase_agent.schemas import (CoupangSearchRequest, CoupangSearchResponse,
    RequestInput, RequestPatch, DocumentBundle, DecisionInput)
from purchase_agent.config import demo_context

@pytest.mark.parametrize('quantity', [True, 0, 21, '3'])
def test_quantity_is_strict_and_bounded(quantity):
    with pytest.raises(ValidationError):
        RequestInput(quantity=quantity, budget_krw=900000)

def test_nullable_purpose_and_patch_semantics():
    assert RequestInput(quantity=3, budget_krw=900000, purpose='  ').purpose is None
    assert RequestPatch(expected_version=1).model_dump(exclude_unset=True) == {'expected_version': 1}
    assert RequestPatch(expected_version=1, purpose=None).model_dump(exclude_unset=True)['purpose'] is None
    with pytest.raises(ValidationError):
        RequestPatch(expected_version=1, quantity=None)

@pytest.mark.parametrize('payload', [{}, {'keyword':' '}, {'keyword':'monitor','limit':11}])
def test_bad_api_request(payload):
    with pytest.raises(ValidationError): CoupangSearchRequest(**payload)

def test_response_modes_and_missing_price():
    envelope = {'rCode':'0','rMessage':'','data':{'landingUrl':'https://www.coupang.com/np/search?q=monitor'}}
    assert CoupangSearchResponse(**envelope).data.productData is None
    envelope['data']['productData'] = []
    assert CoupangSearchResponse(**envelope).data.productData == []
    envelope['data']['productData'] = [{'productId':1,'productName':'synthetic'}]
    with pytest.raises(ValidationError): CoupangSearchResponse(**envelope)
    envelope['data']['productData'] = []
    envelope['data_mode'] = 'mock'
    with pytest.raises(ValidationError): CoupangSearchResponse(**envelope)

def test_incomplete_bundle_cannot_claim_complete():
    with pytest.raises(ValidationError):
        DocumentBundle(request_id='r',version=1,bundle_id='b',review_id='v',policy_version='2',bundle_hash='h',complete=True,files={'review':'text'})

@pytest.mark.parametrize('decision',['reject','request_revision'])
def test_decision_reason_required(decision):
    with pytest.raises(ValidationError): DecisionInput(request_id='r',version=1,decision=decision,reason=' ')

def test_profile_threads_separate_users():
    assert demo_context('employee_a','s').thread_id != demo_context('employee_b','s').thread_id

def test_mock_search_limit_and_link_only_do_not_mutate_snapshot():
    from purchase_agent.coupang_client import MockCoupangClient
    product={'productId':1,'productName':'SYNTHETIC monitor','productPrice':280000,
             'productUrl':'https://www.coupang.com/vp/products/1',
             'productImage':'https://example.com/synthetic.png','isRocket':False,
             'isFreeShipping':True,'keyword':'monitor','rank':1}
    envelope=CoupangSearchResponse(rCode='0',rMessage='',data={'landingUrl':'https://www.coupang.com/np/search?q=monitor','productData':[product,dict(product,productId=2,rank=2)]})
    client=MockCoupangClient({'monitor':envelope})
    assert len(client.search(CoupangSearchRequest(keyword='monitor',limit=1)).data.productData)==1
    assert client.search(CoupangSearchRequest(keyword='monitor',srpLinkOnly=True)).data.productData is None
    assert len(client.search(CoupangSearchRequest(keyword='monitor')).data.productData)==2
    with pytest.raises(LookupError): client.search(CoupangSearchRequest(keyword='unknown'))
