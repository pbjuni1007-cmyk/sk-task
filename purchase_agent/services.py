"""화면에서 사용하는 업무 서비스 계약. 구현은 workflow.LocalPurchaseService에 있다."""

from typing import Protocol, runtime_checkable

from .schemas import (
    ActorContext,
    Confirmation,
    DecisionInput,
    DocumentBundle,
    ListQuery,
    ProductEvidence,
    PurchaseRequest,
    RequestDetail,
    RequestInput,
    RequestPage,
    RequestPatch,
    RequestRef,
    ReviewResult,
    ToolResult,
)


@runtime_checkable
class PurchaseService(Protocol):
    def list_requests(self, context: ActorContext, query: ListQuery) -> ToolResult[RequestPage]: ...
    def get_request(self, context: ActorContext, ref: RequestRef) -> ToolResult[RequestDetail]: ...
    def get_latest_request(
        self, context: ActorContext, request_id: str
    ) -> ToolResult[RequestDetail]: ...
    def create_request(
        self, context: ActorContext, inputs: RequestInput, action_id: str
    ) -> ToolResult[PurchaseRequest]: ...
    def update_request(
        self, context: ActorContext, request_id: str, patch: RequestPatch
    ) -> ToolResult[PurchaseRequest]: ...
    def search_products(
        self,
        context: ActorContext,
        ref: RequestRef,
        keyword: str,
        limit: int = 5,
        refresh: bool = False,
        sort_by: str = "relevance",
    ) -> ToolResult[list[ProductEvidence]]: ...
    def explore_products(
        self, context: ActorContext, keyword: str, limit: int = 10, sort_by: str = "relevance"
    ) -> ToolResult[list[ProductEvidence]]: ...
    def get_department_budget(self, context: ActorContext) -> ToolResult[dict]: ...
    def review_request(
        self, context: ActorContext, ref: RequestRef
    ) -> ToolResult[ReviewResult]: ...
    def generate_documents(
        self, context: ActorContext, ref: RequestRef
    ) -> ToolResult[DocumentBundle]: ...
    def prepare_submission(
        self, context: ActorContext, ref: RequestRef, bundle_id: str
    ) -> ToolResult[Confirmation]: ...
    def submit_request(
        self, context: ActorContext, confirmation: Confirmation
    ) -> ToolResult[PurchaseRequest]: ...
    def decide(
        self, context: ActorContext, decision: DecisionInput
    ) -> ToolResult[PurchaseRequest]: ...
    def download_document(
        self, context: ActorContext, ref: RequestRef, kind: str
    ) -> ToolResult[bytes]: ...
