"""Budgets cover main calls, summary calls and structured-output repair."""
import re
from time import monotonic
from typing import Any
from pydantic import Field
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from langchain.agents.middleware import AgentMiddleware

class BudgetExceeded(RuntimeError): pass

class CallBudget:
    def reset(self):
        self.started=monotonic();self.models=0;self.tools=0;self.repairs=0;self.tokens=0;self.tool_results=[]
    def remaining(self):return 60-(monotonic()-self.started)
    def check(self):
        if self.remaining()<=0:raise BudgetExceeded('TIME_LIMIT')
    def model_call(self):
        self.check()
        if self.models>=6:raise BudgetExceeded('MODEL_LIMIT')
        self.models+=1
    def tool_call(self):
        self.check()
        if self.tools>=10:raise BudgetExceeded('TOOL_LIMIT')
        self.tools+=1
    def repair(self,error):
        self.repairs+=1
        if self.repairs>1:raise BudgetExceeded('OUTPUT_REPAIR_LIMIT')
        return '형식이 잘못되었습니다. 스키마에 맞춰 한 번만 수정하세요.'
    def metrics(self):
        return {'model_attempts':self.models,'tool_attempts':self.tools,'tokens':self.tokens,'elapsed_seconds':round(monotonic()-self.started,3)}

class BudgetModel(BaseChatModel):
    inner: Any = Field(exclude=True,repr=False)
    budget: Any = Field(exclude=True,repr=False)
    secondary: Any = Field(default=None,exclude=True,repr=False)
    @property
    def _llm_type(self):return 'budgeted-model'
    def bind_tools(self,tools,**kwargs):
        return self.model_copy(update={'inner':self.inner.bind_tools(tools,parallel_tool_calls=False,**kwargs),'secondary':self.secondary.bind_tools(tools,parallel_tool_calls=False,**kwargs) if self.secondary is not None else None})
    def _generate(self,messages,stop=None,run_manager=None,**kwargs):
        self.budget.model_call()
        active=self.secondary if getattr(self.budget,'secondary_active',False) and self.secondary is not None else self.inner
        try:
            result=active.invoke(messages,stop=stop,timeout=min(20,max(.1,self.budget.remaining())),**kwargs)
        except Exception as error:
            from openai import APIStatusError
            if not (isinstance(error,APIStatusError) and error.status_code in (401,403,429) and active is self.inner and self.secondary is not None):
                raise
            self.budget.model_call()
            self.budget.secondary_active=True
            result=self.secondary.invoke(messages,stop=stop,timeout=min(20,max(.1,self.budget.remaining())),**kwargs)
        self.budget.tokens+=(result.usage_metadata or {}).get('total_tokens',0)
        self.budget.check()
        return ChatResult(generations=[ChatGeneration(message=result)])

class ToolBudgetMiddleware(AgentMiddleware):
    def __init__(self,budget):self.budget=budget
    def wrap_tool_call(self,request,handler):
        self.budget.tool_call()
        result=handler(request)
        import json
        code=None
        try:code=json.loads(result.content).get('error_code')
        except (ValueError,TypeError,AttributeError):pass
        self.budget.tool_results.append({'tool':request.tool_call['name'],'error_code':code})
        return result

def redact(text):
    text=re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b','[이메일]',text)
    text=re.sub(r'(?<!\d)01[016789][- ]?\d{3,4}[- ]?\d{4}(?!\d)','[전화번호]',text)
    text=re.sub(r'(?<!\d)\d{6}-[1-4]\d{6}(?!\d)','[식별번호]',text)
    return text[:6000]

class WorkflowToolsMiddleware(AgentMiddleware):
    """Only expose tools whose business prerequisites exist at this model step."""
    def __init__(self,session):self.session=session
    def wrap_model_call(self,request,handler):
        allowed={'upsert_purchase_request','save_user_preferences'}
        session=self.session
        if session.current_request:
            current=session.service.get_latest_request(session.context,session.current_request)
            if current.ok:
                d=current.data
                allowed.add('get_request_status')
                allowed.add('search_coupang_products')
                if d.request.selected_evidence_id:
                    allowed.add('review_purchase_request')
                    if d.review:allowed.add('generate_documents')
                    if d.review and d.review.can_submit and d.documents and d.documents.complete and not session.rejected_this_turn and session.submission_requested:
                        allowed.add('submit_purchase_request')
        if session.search_only:
            allowed &= {'upsert_purchase_request','search_coupang_products','get_request_status','save_user_preferences'}
        if session.search_only and session.search_completed:
            allowed=set()
        if session.document_generated:
            allowed={'submit_purchase_request'} if session.submission_requested and not session.rejected_this_turn else set()
        tools=[t for t in request.tools if (getattr(t,'name',None) or (t.get('name') if isinstance(t,dict) else None)) in allowed]
        return handler(request.override(tools=tools))
