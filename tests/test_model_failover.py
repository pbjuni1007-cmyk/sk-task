import pytest
import httpx
from openai import APIStatusError
from langchain_core.messages import AIMessage
from purchase_agent.middleware import BudgetModel,CallBudget,BudgetExceeded

class Stub:
    def __init__(self,error=None):self.error=error;self.calls=0
    def bind_tools(self,*args,**kwargs):return self
    def invoke(self,*args,**kwargs):
        self.calls+=1
        if self.error:raise self.error
        return AIMessage(content='ok')

def error(code):return APIStatusError('redacted',response=httpx.Response(code,request=httpx.Request('POST','https://api.openai.com/v1/chat/completions')),body={})

@pytest.mark.parametrize('code',[401,403,429])
def test_backup_counts_calls_and_stays_active(code):
    primary=Stub(error(code));backup=Stub();budget=CallBudget();budget.reset()
    model=BudgetModel(inner=primary,secondary=backup,budget=budget).bind_tools([])
    assert model.invoke('test').content=='ok'
    assert budget.models==2 and primary.calls==backup.calls==1
    budget.reset();model.invoke('next')
    assert budget.models==1 and primary.calls==1 and backup.calls==2

@pytest.mark.parametrize('code',[400,404,500])
def test_unrelated_error_not_retried_with_another_key(code):
    primary=Stub(error(code));backup=Stub();budget=CallBudget();budget.reset()
    with pytest.raises(APIStatusError):BudgetModel(inner=primary,secondary=backup,budget=budget).invoke('test')
    assert backup.calls==0 and budget.models==1

def test_both_keys_fail_without_loop():
    budget=CallBudget();budget.reset();a=Stub(error(429));b=Stub(error(429))
    with pytest.raises(APIStatusError):BudgetModel(inner=a,secondary=b,budget=budget).invoke('test')
    assert a.calls==b.calls==1 and budget.models==2

def test_no_budget_for_backup():
    budget=CallBudget();budget.reset();budget.models=5;a=Stub(error(429));b=Stub()
    with pytest.raises(BudgetExceeded):BudgetModel(inner=a,secondary=b,budget=budget).invoke('test')
    assert b.calls==0 and budget.models==6
