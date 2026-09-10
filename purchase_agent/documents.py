"""Render a single version into an atomic three-document bundle."""
import hashlib
import json
from uuid import uuid4
from .schemas import RequestDetail, DocumentBundle

def safe(value):
    import html
    return html.escape(str(value)).replace('|','&#124;').replace('\n',' ')

def render(detail: RequestDetail) -> DocumentBundle:
    request, review = detail.request, detail.review
    if review is None or not request.selected_evidence_id:
        raise ValueError('REVIEW_REQUIRED')
    money = lambda x: '확인 필요' if x is None else f'{x:,}원'
    header = f'요청번호: {request.request_id} / 버전: {request.version}\n\n상품금액: {money(review.subtotal_krw)} / 배송비: {money(review.shipping_fee_krw)} / 총액: {money(review.review_total_krw)}\n\n'
    selected = next(e for e in detail.candidates if e.evidence_id == request.selected_evidence_id)
    header += f'선택 상품: {safe(selected.product.productName)} / 수량: {request.inputs.quantity} / 단가: {money(selected.product.productPrice)}\n\n'
    files = {
        'purchase_request': '# 구매요청서\n\n'+header+f'목적: {safe(request.inputs.purpose or "제출 전 입력 필요")}\n\n상품: {safe(selected.product.productName)}\n\n수량: {request.inputs.quantity}\n\n예산: {money(request.inputs.budget_krw)}\n\n상품 링크: {selected.product.productUrl}\n',
        'comparison': '# 상품 비교표\n\n'+header+'| 상품 | 단가 | 링크 |\n|---|---:|---|\n'+''.join(f'| {safe(e.product.productName)} | {money(e.product.productPrice)} | {e.product.productUrl} |\n' for e in detail.candidates),
        'review': '# 규정 검토 보고서\n\n'+header+'\n'.join(f'- {c.policy_id}: {c.result} — {safe(c.reason)}' for c in review.checks),
    }
    for key in files:
        files[key]+='\n\n모의 API 데이터 기준. 실제 주문·결제 문서가 아닙니다.\n'
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return DocumentBundle(request_id=request.request_id,version=request.version,bundle_id=uuid4().hex,
        review_id=review.review_id,policy_version=review.policy_version,bundle_hash=digest,complete=True,files=files)
