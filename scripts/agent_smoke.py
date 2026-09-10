"""Authorized real-model + tool smoke, no shopping API call or real submission."""
import sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from purchase_agent.agent import AgentSession
from purchase_agent.workflow import LocalPurchaseService
from purchase_agent.config import demo_context
from purchase_agent.schemas import ListQuery
with tempfile.TemporaryDirectory() as directory:
    service=LocalPurchaseService(Path(directory)/'smoke.db')
    context=demo_context('employee_a','live-smoke')
    session=AgentSession(service,context)
    result=session.invoke('개발팀 신입 3명 업무용 모니터를 배송비 포함 90만원 이내로 구매하려고 해. 수량과 예산, 목적을 저장하고 후보를 찾아줘. 상품 자료가 없으면 없다고 안내해.')
    output=result.get('response')
    saved=service.list_requests(context,ListQuery()).data
    print({'status':output.status if output else 'pending','saved_requests':saved.total,'metrics':result['metrics'],'tool_results':session.budget.tool_results})
    if output is None or output.status=='failed' or saved.total!=1:sys.exit(1)
