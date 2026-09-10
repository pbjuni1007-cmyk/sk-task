"""Seven LLM tools, all bound to a server-owned session context."""
from langchain_core.tools import tool
from .schemas import RequestInput, RequestPatch, RequestRef, ToolResult


class ToolStop(RuntimeError):
    pass

def build_tools(session):
    service,ctx=session.service,session.context
    def result(value):return value.model_dump(mode='json')
    def failure(code):return result(ToolResult(ok=False,error_code=code))
    def ref(request_id,version):return RequestRef(request_id=request_id,version=version)

    @tool
    def upsert_purchase_request(quantity:int|None=None,budget_krw:int|None=None,purpose:str|None=None,requirements:list[str]|None=None,selected_evidence_id:str|None=None,request_id:str|None=None,expected_version:int|None=None,clear_purpose:bool=False,clear_selection:bool=False):
        """Save monitor conditions. Creation requires integer quantity (1-20) and budget_krw. Purpose optional. Omit unchanged fields on updates, which require request_id and latest expected_version. Select only returned selected_evidence_id. Never supply price/actor/status."""
        if session.search_only and (selected_evidence_id is not None or clear_selection):
            return failure('SEARCH_ONLY: selection changes require a separate user request')
        values={key:value for key,value in {'quantity':quantity,'budget_krw':budget_krw,'purpose':purpose,'requirements':requirements,'selected_evidence_id':selected_evidence_id}.items() if value is not None}
        if clear_purpose:values['purpose']=None
        if clear_selection:values['selected_evidence_id']=None
        try:
            if request_id is None:
                value=service.create_request(ctx,RequestInput.model_validate(values),session.action_id)
            else:
                value=service.update_request(ctx,request_id,RequestPatch.model_validate({**values,'expected_version':expected_version}))
            if value.ok:session.current_request=value.data.request_id
            elif value.error_code=='UNKNOWN_PRODUCT' and request_id:
                latest=service.get_latest_request(ctx,request_id)
                if latest.ok:
                    return failure('UNKNOWN_PRODUCT: use selected_evidence_id exactly from '+str([e.evidence_id for e in latest.data.candidates]))
            return result(value)
        except ValueError:return failure('INVALID_INPUT: quantity 1-20, budget_krw positive integer; update needs expected_version')

    @tool
    def search_coupang_products(request_id:str,version:int,keyword:str,limit:int=5,refresh:bool=False):
        """Search mock Coupang data. Catalog can be unavailable; never invent products. Refresh can create a new request version: call get_request_status afterwards."""
        # This practice searches a monitor-only snapshot. Natural descriptions
        # such as '업무용 모니터' use its category; hard specs remain policy inputs.
        query='모니터' if '모니터' in keyword else keyword
        value=service.search_products(ctx,ref(request_id,version),query,limit,refresh)
        if not value.ok:raise ToolStop(value.error_code)
        latest=service.get_latest_request(ctx,request_id)
        session.search_completed=True
        preferences=service.get_preferences(ctx)
        from .preferences import order_candidates
        value.data=order_candidates(value.data,preferences.data if preferences.ok else {},latest.data.request.inputs)
        if not value.data:raise ToolStop('EMPTY_CANDIDATES')
        return result(ToolResult(ok=True,data={'candidates':value.data,'selection_keys':[{'selected_evidence_id':e.evidence_id,'productName':e.product.productName} for e in value.data],'request_id':request_id,'version':latest.data.request.version}))

    @tool
    def review_purchase_request(request_id:str,version:int):
        """Calculate shipping-inclusive total and policy checks from stored evidence. Missing purpose/shipping blocks submission but permits a draft."""
        if session.search_only:return failure('SEARCH_ONLY')
        return result(service.review_request(ctx,ref(request_id,version)))

    @tool
    def generate_documents(request_id:str,version:int):
        """Generate three Markdown documents from the version's review. Call review first; no invented amount or purpose."""
        if session.search_only:return failure('SEARCH_ONLY')
        value=service.generate_documents(ctx,ref(request_id,version))
        if value.ok:session.document_generated=True
        return result(value)

    @tool
    def submit_purchase_request(request_id:str,version:int,bundle_id:str):
        """Propose internal submission of an existing ready bundle. Must interrupt and receive the user's explicit UI confirmation; never purchase or pay."""
        if not session.submission_requested:return failure('SUBMISSION_NOT_REQUESTED')
        confirmation=session.confirmation
        if not confirmation or (confirmation.request_id,confirmation.version,confirmation.bundle_id)!=(request_id,version,bundle_id):return failure('CONFIRMATION_REQUIRED')
        value=service.submit_request(ctx,confirmation)
        session.confirmation=None
        return result(value)

    @tool
    def get_request_status(request_id:str):
        """Read authorized latest request, version, evidence, documents and approval history."""
        value=service.get_latest_request(ctx,request_id)
        if value.ok:session.current_request=request_id
        return result(value)

    @tool
    def save_user_preferences(comparison_priority:str='price',output_style:str='concise'):
        """Save non-sensitive preferences only when the user checked consent in this UI event. priority: price/specification; style: concise/detailed."""
        return result(service.save_preferences(ctx,{'comparison_priority':comparison_priority,'output_style':output_style},consent=session.preference_consent))

    return [upsert_purchase_request,search_coupang_products,review_purchase_request,generate_documents,submit_purchase_request,get_request_status,save_user_preferences]
