import pytest
from purchase_agent.coupang_client import MockCoupangClient, SearchError, RateWindow
from purchase_agent.schemas import CoupangSearchRequest,CoupangSearchResponse

def client(**kwargs):
    return MockCoupangClient({'x':CoupangSearchResponse(rCode='0',rMessage='',data={'landingUrl':'https://www.coupang.com/np/search','productData':[]})},**kwargs)
Q=CoupangSearchRequest(keyword='x')
@pytest.mark.parametrize('code,expected',[ (500,2),('timeout',2),(429,2),(403,1),(400,1)])
def test_error_retry_is_bounded(code,expected):
    c=client(errors=[SearchError(code),SearchError(code)])
    with pytest.raises(SearchError):c.search(Q)
    assert c.attempts==expected

def test_recover_once_and_cache():
    c=client(errors=[SearchError(500)])
    assert c.search(Q).data.productData==[]
    assert c.attempts==2
    c.search(Q);assert c.attempts==2
    c.search(Q,refresh=True);assert c.attempts==3

def test_shared_rate_window_and_reset():
    now=[0.0];window=RateWindow(clock=lambda:now[0])
    a=client(rate_window=window);b=client(rate_window=window)
    for _ in range(50):a.search(Q,refresh=True)
    with pytest.raises(SearchError):b.search(Q)
    now[0]=60
    assert b.search(Q).data.productData==[]

def test_retry_after_does_not_sleep_past_budget():
    c=client(errors=[SearchError(429,retry_after=120)])
    with pytest.raises(SearchError):c.search(Q)
    assert c.attempts==1
