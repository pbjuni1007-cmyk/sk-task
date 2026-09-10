"""Offline compatibility checks; not a real model quality/latency evaluation."""
from typing import Any
import pytest
from pydantic import Field
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, SummarizationMiddleware
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from purchase_agent.schemas import PurchaseAssistantResponse

class ScriptModel(BaseChatModel):
    responses: list[AIMessage] = Field(default_factory=list)
    index: int = 0
    @property
    def _llm_type(self): return 'offline-script'
    def bind_tools(self, tools, **kwargs): return self
    def _generate(self, messages, stop=None, run_manager=None, **kwargs: Any):
        response = self.responses[self.index]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])

@pytest.mark.parametrize('decision,expected', [('approve',1),('reject',0)])
def test_interrupt_before_tool_and_resume(decision, expected):
    calls=[]
    def submit_purchase_request(request_id: str) -> str:
        """Record an offline submission for compatibility testing only."""
        calls.append(request_id)
        return 'recorded'
    model=ScriptModel(responses=[AIMessage(content='',tool_calls=[{'name':'submit_purchase_request','args':{'request_id':'r'},'id':'call1'}]),AIMessage(content='finished')])
    graph=create_agent(model=model,tools=[submit_purchase_request],middleware=[HumanInTheLoopMiddleware(interrupt_on={'submit_purchase_request':{'allowed_decisions':['approve','reject']}})],checkpointer=InMemorySaver())
    config={'configurable':{'thread_id':decision}}
    result=graph.invoke({'messages':[{'role':'user','content':'submit'}]},config)
    assert result['__interrupt__'] and calls == []
    graph.invoke(Command(resume={'decisions':[{'type':decision}]}),config)
    assert len(calls)==expected

def test_structured_output_and_summary_constructor():
    payload={'status':'needs_input','message':'수량을 입력하세요','request_id':None,'version':None,'missing_fields':['quantity'],'candidate_ids':[],'review_id':None,'document_bundle_id':None,'submitted_at':None,'warnings':['mock']}
    model=ScriptModel(responses=[AIMessage(content='',tool_calls=[{'name':'PurchaseAssistantResponse','args':payload,'id':'structured1'}])])
    graph=create_agent(model=model,response_format=ToolStrategy(PurchaseAssistantResponse))
    result=graph.invoke({'messages':[{'role':'user','content':'start'}]})
    assert result['structured_response'].status=='needs_input'
    # Constructor/import compatibility only; summarization behavior belongs to S4.
    assert SummarizationMiddleware(model=ScriptModel(responses=[]),trigger=('messages',20),keep=('messages',6))
