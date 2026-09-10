"""Offline transport with bounded retry, cache, and shared per-key rate window."""
from collections import defaultdict, deque
from threading import Lock
from time import monotonic
from .schemas import CoupangSearchRequest, CoupangSearchResponse

class SearchError(Exception):
    def __init__(self,code,retry_after=0):
        super().__init__(str(code));self.code=code;self.retry_after=retry_after

class RateWindow:
    def __init__(self,clock=monotonic):
        self.clock=clock;self.calls=defaultdict(deque);self.lock=Lock()
    def acquire(self,key):
        with self.lock:
            now=self.clock();calls=self.calls[key]
            while calls and now-calls[0]>=60:calls.popleft()
            if len(calls)>=50:raise SearchError(429)
            calls.append(now)

class MockCoupangClient:
    """Explicit snapshots only. Error scripts are for deterministic tests."""
    def __init__(self,fixtures,*,rate_window=None,key='mock',clock=monotonic,errors=()):
        self._fixtures={k:v.model_copy(deep=True) for k,v in fixtures.items()}
        self.rate_window=rate_window or RateWindow(clock)
        self.key=key;self.clock=clock;self.errors=deque(errors);self.cache={};self.attempts=0
    def search(self,request:CoupangSearchRequest,*,refresh=False,deadline=None):
        cache_key=request.model_dump_json(exclude_none=True)
        if not refresh and cache_key in self.cache:return self.cache[cache_key].model_copy(deep=True)
        for attempt in range(2):
            if deadline is not None and self.clock()>=deadline:raise SearchError('timeout')
            self.rate_window.acquire(self.key);self.attempts+=1
            error=self.errors.popleft() if self.errors else None
            if error:
                if attempt==0 and error.code in (429,500,'timeout') and not error.retry_after:continue
                raise error
            if request.keyword not in self._fixtures:raise LookupError('FIXTURE_NOT_CONFIGURED')
            result=self._fixtures[request.keyword].model_copy(deep=True)
            if request.srpLinkOnly:result.data.productData=None
            elif result.data.productData is None:raise ValueError('PRODUCT_LIST_MISSING')
            else:result.data.productData=result.data.productData[:request.limit]
            self.cache[cache_key]=result.model_copy(deep=True)
            return result
