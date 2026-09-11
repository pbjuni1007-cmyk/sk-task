"""Shared contract v1; API wire models never contain internal evidence metadata."""

from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Positive = Annotated[int, Field(strict=True, gt=0)]
Money = Annotated[int, Field(strict=True, ge=0)]
Quantity = Annotated[int, Field(strict=True, ge=1, le=20)]
Role = Literal["requester", "buyer", "manager"]
Status = Literal[
    "draft", "ready", "submitted", "additional_approval", "approved", "rejected", "needs_revision"
]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ActorContext(Model):
    """Construct from server profiles, never from model/UI role arguments."""

    actor_id: str
    department_id: str
    role: Role
    thread_id: str


class RequestRef(Model):
    request_id: str
    version: Positive


class RequestInput(Model):
    quantity: Quantity
    budget_krw: Positive
    requirements: list[str] = Field(default_factory=list)
    purpose: str | None = Field(default=None, max_length=500)
    item_type: Literal["monitor"] = "monitor"

    @field_validator("purpose", mode="before")
    @classmethod
    def clean_purpose(cls, value):
        return value.strip() or None if isinstance(value, str) else value


class DraftInput(Model):
    """검색 전 수집 중인 조건. 정식 요청은 여전히 수량·예산이 필수다."""

    quantity: Quantity | None = None
    budget_krw: Positive | None = None
    purpose: str | None = Field(default=None, max_length=500)
    requirements: list[str] = Field(default_factory=list)


class RequestPatch(Model):
    """Use model_dump(exclude_unset=True): omission keeps, explicit null clears."""

    expected_version: Positive
    quantity: Quantity | None = None
    budget_krw: Positive | None = None
    requirements: list[str] | None = None
    purpose: str | None = Field(default=None, max_length=500)
    selected_evidence_id: str | None = None
    _clean = field_validator("purpose", mode="before")(RequestInput.clean_purpose.__func__)

    @model_validator(mode="after")
    def required_values_not_cleared(self):
        for key in ("quantity", "budget_krw", "requirements"):
            if key in self.model_fields_set and getattr(self, key) is None:
                raise ValueError(f"{key} cannot be cleared")
        return self


class CoupangSearchRequest(Model):
    keyword: str = Field(min_length=1)
    limit: Annotated[int, Field(strict=True, ge=1, le=10)] = 10
    subId: str | None = None
    imageSize: str | None = None
    srpLinkOnly: bool = False

    @field_validator("keyword")
    @classmethod
    def nonblank(cls, v):
        if not v.strip():
            raise ValueError("keyword must not be blank")
        return v.strip()


class CoupangProduct(Model):
    productId: Positive
    productName: str
    productPrice: Money
    productUrl: HttpUrl
    productImage: HttpUrl
    isRocket: bool
    isFreeShipping: bool
    keyword: str
    rank: Positive


class CoupangSearchData(Model):
    landingUrl: HttpUrl
    productData: list[CoupangProduct] | None = None


class CoupangSearchResponse(Model):
    rCode: Literal["0"]
    rMessage: str
    data: CoupangSearchData


class ShippingTier(Model):
    min_quantity: Quantity
    max_quantity: Quantity
    fee_krw: Money

    @model_validator(mode="after")
    def ordered(self):
        if self.min_quantity > self.max_quantity:
            raise ValueError("invalid quantity interval")
        return self


class ProductSupplement(Model):
    product_id: Positive
    item_id: str | None = None
    vendor_item_id: str | None = None
    option_label: str | None = None
    verified_specs: list[str] = Field(default_factory=list)
    shipping_rule: Literal["free", "per_order", "per_item", "tiered"] | None = None
    fee_krw: Money | None = None
    tiers: list[ShippingTier] = Field(default_factory=list)
    shipping_source_url: HttpUrl | None = None
    source_checked_at: datetime | None = None
    source_status: Literal["verified", "indexed_only", "unverified"] = "unverified"


class ProductEvidence(Model):
    evidence_id: str
    product: CoupangProduct
    supplement: ProductSupplement
    query: str
    retrieved_at: datetime
    fixture_version: str
    data_mode: Literal["mock"] = "mock"

    @model_validator(mode="after")
    def same_product(self):
        if self.product.productId != self.supplement.product_id:
            raise ValueError("product and supplement mismatch")
        return self


class PolicyCheck(Model):
    policy_id: str
    result: Literal["pass", "fail", "unknown"]
    reason: str


class ReviewResult(RequestRef):
    review_id: str
    policy_version: str
    subtotal_krw: Money
    shipping_fee_krw: Money | None
    review_total_krw: Money | None
    remaining_krw: int | None
    checks: list[PolicyCheck]
    required_approvers: list[Role]
    can_submit: bool
    missing_fields: list[str] = Field(default_factory=list)


class DocumentBundle(RequestRef):
    bundle_id: str
    review_id: str
    policy_version: str
    bundle_hash: str
    complete: bool
    files: dict[Literal["purchase_request", "comparison", "review"], str]

    @model_validator(mode="after")
    def all_documents_when_complete(self):
        if self.complete and (
            set(self.files) != {"purchase_request", "comparison", "review"}
            or not all(self.files.values())
        ):
            raise ValueError("complete bundle requires three nonempty documents")
        return self


class PurchaseRequest(RequestRef):
    owner_id: str
    department_id: str
    inputs: RequestInput
    status: Status = "draft"
    selected_evidence_id: str | None = None
    submitted_at: datetime | None = None
    submitted_bundle_id: str | None = None


class ApprovalEvent(RequestRef):
    actor_id: str
    decision: Literal["submit", "approve", "reject", "request_revision"]
    reason: str | None = None
    created_at: datetime


class RequestDetail(Model):
    request: PurchaseRequest
    candidates: list[ProductEvidence] = Field(default_factory=list)
    review: ReviewResult | None = None
    documents: DocumentBundle | None = None
    history: list[ApprovalEvent] = Field(default_factory=list)
    allowed_actions: list[str] = Field(default_factory=list)
    blocked_reasons: list[str] = Field(default_factory=list)


class ListQuery(Model):
    folder: Literal["mine", "pending", "revision", "completed"] = "mine"
    keyword: str = ""
    department_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    page: Positive = 1
    page_size: Annotated[int, Field(strict=True, ge=1, le=100)] = 20


class RequestPage(Model):
    items: list[RequestDetail]
    total: Money


class Confirmation(RequestRef):
    """Opaque token for server/UI bridge only; never an LLM tool argument."""

    token: str
    bundle_id: str


class DecisionInput(RequestRef):
    decision: Literal["approve", "reject", "request_revision"]
    reason: str | None = None

    @model_validator(mode="after")
    def reason_required(self):
        if self.decision != "approve" and not (self.reason and self.reason.strip()):
            raise ValueError("reason required")
        return self


T = TypeVar("T")


class ToolResult(Model, Generic[T]):
    ok: bool
    data: T | None = None
    error_code: str | None = None
    retryable: bool = False

    @model_validator(mode="after")
    def consistent(self):
        if self.ok and (self.error_code is not None or self.retryable):
            raise ValueError("success cannot carry an error")
        if not self.ok and (not self.error_code or self.data is not None):
            raise ValueError("failure requires code and no data")
        return self


class PurchaseAssistantResponse(Model):
    status: Literal[
        "needs_input",
        "candidates_ready",
        "needs_revision",
        "documents_ready",
        "submitted",
        "blocked",
        "failed",
    ]
    message: str
    request_id: str | None
    version: Positive | None
    missing_fields: list[str]
    candidate_ids: list[int]
    review_id: str | None
    document_bundle_id: str | None
    submitted_at: datetime | None
    warnings: list[str]
