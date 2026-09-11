"""Business service. UI/LLM never bypass transaction, ownership or current-version gates."""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from functools import wraps
from uuid import uuid4

from . import documents, policy
from .coupang_client import MockCoupangClient, RateWindow, SearchError
from .schemas import (
    ApprovalEvent,
    Confirmation,
    CoupangSearchData,
    CoupangSearchRequest,
    CoupangSearchResponse,
    ProductEvidence,
    PurchaseRequest,
    RequestDetail,
    RequestInput,
    RequestPage,
    RequestRef,
    ToolResult,
)
from .storage import Database


class BusinessError(Exception):
    pass


def operation(fn):
    # UI와 Agent의 모든 업무 호출을 같은 권한 검사·DB 트랜잭션·오류 형식으로 감싼다.
    @wraps(fn)
    def wrapped(self, *args, **kwargs):
        try:
            context = kwargs.get("context", args[0] if args else None)
            if context is not None:
                from .config import DEMO_PROFILES

                profile = DEMO_PROFILES.get(context.actor_id)
                if profile != (
                    context.department_id,
                    context.role,
                ) or not context.thread_id.startswith(context.actor_id + ":"):
                    raise BusinessError("INVALID_CONTEXT")
            with self.db.transaction() as db:
                return ToolResult(ok=True, data=fn(self, db, *args, **kwargs))
        except (BusinessError, ValueError, LookupError) as e:
            return ToolResult(ok=False, error_code=str(e))
        except SearchError as e:
            return ToolResult(ok=False, error_code=f"SEARCH_{e.code}", retryable=False)
        except sqlite3.Error:
            return ToolResult(ok=False, error_code="STORAGE_ERROR", retryable=True)

    return wrapped


class LocalPurchaseService:
    def __init__(self, path, catalog=()):
        self.db = Database(path)
        self.catalog = [ProductEvidence.model_validate(e).model_copy(deep=True) for e in catalog]
        self.boot = uuid4().hex
        self.rate_window = RateWindow()
        self._search_clients = {}

    def _get(self, db, ctx, ref, owner=False, current=False):
        head = db.execute("SELECT * FROM requests WHERE id=?", (ref.request_id,)).fetchone()
        if not head:
            raise BusinessError("NOT_FOUND")
        if head["owner"] != ctx.actor_id and (owner or ctx.role == "requester"):
            raise BusinessError("FORBIDDEN")
        if current and head["version"] != ref.version:
            raise BusinessError("STALE_VERSION")
        row = db.execute(
            "SELECT body FROM versions WHERE id=? AND version=?", (ref.request_id, ref.version)
        ).fetchone()
        if not row:
            raise BusinessError("NOT_FOUND")
        return RequestDetail.model_validate_json(row["body"])

    def _save(self, db, d):
        db.execute(
            "INSERT OR REPLACE INTO versions VALUES(?,?,?)",
            (d.request.request_id, d.request.version, d.model_dump_json()),
        )

    def _decorate(self, d, ctx, current=True):
        d.allowed_actions = []
        r = d.request
        if current and r.owner_id == ctx.actor_id:
            d.allowed_actions = ["update", "search"]
            if r.status in ("draft", "ready"):
                d.allowed_actions += ["review", "generate"]
                if r.status == "ready":
                    d.allowed_actions += ["submit"]
        if current and r.owner_id != ctx.actor_id:
            if ctx.role == "buyer" and r.status == "submitted":
                d.allowed_actions += ["approve", "reject", "request_revision"]
            if ctx.role == "manager" and r.status == "additional_approval":
                d.allowed_actions += ["approve", "reject"]
        d.blocked_reasons = (
            [] if d.review is None else [c.reason for c in d.review.checks if c.result != "pass"]
        )
        return d

    @operation
    def create_request(self, db, context, inputs, action_id):
        old = db.execute(
            "SELECT request_id FROM actions WHERE actor=? AND action=?",
            (context.actor_id, action_id),
        ).fetchone()
        if old:
            head = db.execute("SELECT version FROM requests WHERE id=?", (old[0],)).fetchone()
            return self._get(
                db, context, RequestRef(request_id=old[0], version=head[0]), owner=True
            ).request
        r = PurchaseRequest(
            request_id=uuid4().hex,
            version=1,
            owner_id=context.actor_id,
            department_id=context.department_id,
            inputs=inputs,
        )
        db.execute("INSERT INTO requests VALUES(?,?,?)", (r.request_id, r.owner_id, 1))
        db.execute("INSERT INTO actions VALUES(?,?,?)", (context.actor_id, action_id, r.request_id))
        self._save(db, RequestDetail(request=r))
        return r

    def _new_version(self, db, d, inputs, selected, candidates):
        # 이전 검토·문서는 그대로 남기고 변경된 조건의 작업 버전을 별도로 저장한다.
        r = d.request.model_copy(
            update={
                "version": d.request.version + 1,
                "inputs": inputs,
                "selected_evidence_id": selected,
                "status": "draft",
                "submitted_at": None,
                "submitted_bundle_id": None,
            }
        )
        result = RequestDetail(request=r, candidates=candidates)
        db.execute("UPDATE requests SET version=? WHERE id=?", (r.version, r.request_id))
        self._save(db, result)
        return result

    @operation
    def update_request(self, db, context, request_id, patch):
        d = self._get(
            db,
            context,
            RequestRef(request_id=request_id, version=patch.expected_version),
            owner=True,
            current=True,
        )
        values = patch.model_dump(exclude_unset=True)
        values.pop("expected_version")
        selected = values.pop("selected_evidence_id", d.request.selected_evidence_id)
        if selected is not None and selected not in {e.evidence_id for e in d.candidates}:
            raise BusinessError("UNKNOWN_PRODUCT")
        inputs = RequestInput.model_validate({**d.request.inputs.model_dump(), **values})
        if inputs == d.request.inputs and selected == d.request.selected_evidence_id:
            return d.request
        return self._new_version(db, d, inputs, selected, d.candidates).request

    @operation
    def get_request(self, db, context, ref):
        d = self._get(db, context, ref)
        current = (
            db.execute("SELECT version FROM requests WHERE id=?", (ref.request_id,)).fetchone()[0]
            == ref.version
        )
        return self._decorate(d, context, current)

    @operation
    def get_latest_request(self, db, context, request_id):
        row = db.execute("SELECT version FROM requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise BusinessError("NOT_FOUND")
        d = self._get(db, context, RequestRef(request_id=request_id, version=row[0]))
        return self._decorate(d, context)

    @operation
    def list_requests(self, db, context, query):
        items = []
        for row in db.execute(
            "SELECT v.body FROM versions v JOIN requests r ON v.id=r.id AND v.version=r.version ORDER BY r.rowid DESC"
        ):
            d = RequestDetail.model_validate_json(row[0])
            r = d.request
            if context.role == "requester" and r.owner_id != context.actor_id:
                continue
            if query.folder == "mine" and r.owner_id != context.actor_id:
                continue
            if query.folder == "pending" and (
                r.owner_id == context.actor_id
                or not (
                    (context.role == "buyer" and r.status == "submitted")
                    or (context.role == "manager" and r.status == "additional_approval")
                )
            ):
                continue
            if query.folder == "revision" and (
                r.owner_id != context.actor_id or r.status != "needs_revision"
            ):
                continue
            if query.folder == "completed" and r.status not in ("approved", "rejected"):
                continue
            if query.department_id and r.department_id != query.department_id:
                continue
            if (
                query.keyword.casefold()
                not in (r.request_id + " " + (r.inputs.purpose or "")).casefold()
            ):
                continue
            if query.date_from and (r.submitted_at is None or r.submitted_at < query.date_from):
                continue
            if query.date_to and (r.submitted_at is None or r.submitted_at > query.date_to):
                continue
            items.append(self._decorate(d, context))
        start = (query.page - 1) * query.page_size
        return RequestPage(items=items[start : start + query.page_size], total=len(items))

    @staticmethod
    def _evidence_hash(items):
        bodies = []
        for e in items:
            b = e.model_dump(mode="json")
            b.pop("retrieved_at")
            b.pop("evidence_id")
            bodies.append(b)
        return hashlib.sha256(json.dumps(bodies, sort_keys=True).encode()).hexdigest()

    @operation
    def search_products(self, db, context, ref, keyword, limit=5, refresh=False):
        query = CoupangSearchRequest(keyword=keyword, limit=limit)
        d = self._get(db, context, ref, owner=True, current=True)
        if not self.catalog:
            raise BusinessError("CATALOG_NOT_VERIFIED")
        candidates = [
            e.model_copy(deep=True)
            for e in self.catalog
            if query.keyword.casefold() in (e.query + " " + e.product.productName).casefold()
        ]
        for e in candidates:
            e.query = query.keyword
            e.retrieved_at = datetime.now(timezone.utc)
        response = CoupangSearchResponse(
            rCode="0",
            rMessage="",
            data=CoupangSearchData(
                landingUrl="https://www.coupang.com/np/search",
                productData=[e.product for e in candidates],
            ),
        )
        cache_key = (query.keyword, self._evidence_hash(candidates))
        if cache_key not in self._search_clients:
            if len(self._search_clients) >= 100:
                self._search_clients.clear()
            self._search_clients[cache_key] = MockCoupangClient(
                {query.keyword: response}, rate_window=self.rate_window
            )
        wire = self._search_clients[cache_key].search(query, refresh=refresh)
        remaining = list(candidates)
        candidates = []
        for product in wire.data.productData:
            index = next((i for i, e in enumerate(remaining) if e.product == product), None)
            if index is None:
                raise BusinessError("EVIDENCE_MISMATCH")
            candidates.append(remaining.pop(index))
        if not candidates:
            return []
        if self._evidence_hash(d.candidates) != self._evidence_hash(candidates):
            if d.candidates or d.request.status not in ("draft", "ready"):
                selected = next(
                    (
                        e.evidence_id
                        for e in candidates
                        if any(
                            old.evidence_id == d.request.selected_evidence_id
                            and old.product.productId == e.product.productId
                            and old.supplement.item_id == e.supplement.item_id
                            and old.supplement.vendor_item_id == e.supplement.vendor_item_id
                            for old in d.candidates
                        )
                    ),
                    None,
                )
                self._new_version(db, d, d.request.inputs, selected, candidates)
            else:
                d.candidates = candidates
                d.review = None
                d.documents = None
                d.request.status = "draft"
                self._save(db, d)
        return candidates

    @operation
    def review_request(self, db, context, ref):
        # 조건·후보 변경은 다른 진입점에서 새 버전이 된다. 같은 정책의 재검토는 보존한다.
        d = self._get(db, context, ref, owner=True, current=True)
        if d.request.status in (
            "submitted",
            "additional_approval",
            "approved",
            "rejected",
            "needs_revision",
        ):
            if d.review:
                return d.review
            raise BusinessError("FROZEN_VERSION")
        if d.review:
            if d.review.policy_version == policy.POLICY_VERSION:
                return d.review
            d = self._new_version(
                db, d, d.request.inputs, d.request.selected_evidence_id, d.candidates
            )
        d.review = policy.review(d.request, d.candidates)
        d.documents = None
        d.request.status = "draft"
        self._save(db, d)
        return d.review

    @operation
    def generate_documents(self, db, context, ref):
        d = self._get(db, context, ref, owner=True, current=True)
        if d.request.status in (
            "submitted",
            "additional_approval",
            "approved",
            "rejected",
            "needs_revision",
        ):
            if d.documents:
                return d.documents
            raise BusinessError("FROZEN_VERSION")
        d.documents = documents.render(d)
        d.request.status = "ready" if d.review.can_submit else "draft"
        self._save(db, d)
        return d.documents

    @operation
    def prepare_submission(self, db, context, ref, bundle_id):
        # 화면에서 확인할 버전·문서 해시를 사용자와 대화에 묶어 제출 토큰을 발급한다.
        d = self._get(db, context, ref, owner=True, current=True)
        if (
            d.request.status != "ready"
            or not d.review
            or not d.review.can_submit
            or not d.documents
            or not d.documents.complete
            or d.documents.bundle_id != bundle_id
        ):
            raise BusinessError("NOT_READY")
        c = Confirmation(
            request_id=ref.request_id, version=ref.version, bundle_id=bundle_id, token=uuid4().hex
        )
        db.execute(
            "INSERT INTO confirmations VALUES(?,?,?,?,?,?,?,?,0)",
            (
                c.token,
                context.actor_id,
                context.thread_id,
                ref.request_id,
                ref.version,
                bundle_id,
                d.documents.bundle_hash,
                self.boot,
            ),
        )
        return c

    @operation
    def submit_request(self, db, context, confirmation):
        # 확인 후 조건이나 문서가 바뀌었는지 재검사한다. 확인 화면만으로 제출을 허용하지 않는다.
        d = self._get(db, context, confirmation, owner=True, current=True)
        c = db.execute(
            "SELECT * FROM confirmations WHERE token=?", (confirmation.token,)
        ).fetchone()
        if not c or any(
            (
                c["actor"] != context.actor_id,
                c["thread"] != context.thread_id,
                c["request_id"] != confirmation.request_id,
                c["version"] != confirmation.version,
                c["bundle"] != confirmation.bundle_id,
            )
        ):
            raise BusinessError("CONFIRMATION_REQUIRED")
        if d.request.submitted_at and d.request.submitted_bundle_id == confirmation.bundle_id:
            return d.request
        if c["boot"] != self.boot or c["consumed"]:
            raise BusinessError("CONFIRMATION_EXPIRED")
        if d.documents and d.review:
            recalculated = policy.review(d.request, d.candidates)
            compared = (
                "subtotal_krw",
                "shipping_fee_krw",
                "review_total_krw",
                "remaining_krw",
                "policy_version",
                "required_approvers",
            )
            if any(getattr(recalculated, k) != getattr(d.review, k) for k in compared):
                raise BusinessError("STALE_REVIEW")
            if documents.render(d).bundle_hash != d.documents.bundle_hash:
                raise BusinessError("DOCUMENT_MISMATCH")
            actual_hash = hashlib.sha256(
                json.dumps(d.documents.files, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()
            if actual_hash != d.documents.bundle_hash:
                raise BusinessError("DOCUMENT_MISMATCH")
        if (
            d.request.status != "ready"
            or not d.documents
            or not d.documents.complete
            or d.documents.bundle_id != c["bundle"]
            or d.documents.bundle_hash != c["hash"]
            or not d.review
            or not policy.review(d.request, d.candidates).can_submit
        ):
            raise BusinessError("NOT_READY")
        d.request.status = "submitted"
        d.request.submitted_at = datetime.now(timezone.utc)
        d.request.submitted_bundle_id = confirmation.bundle_id
        d.history.append(
            ApprovalEvent(
                request_id=d.request.request_id,
                version=d.request.version,
                actor_id=context.actor_id,
                decision="submit",
                created_at=d.request.submitted_at,
            )
        )
        db.execute("UPDATE confirmations SET consumed=1 WHERE token=?", (confirmation.token,))
        self._save(db, d)
        return d.request

    @operation
    def decide(self, db, context, decision):
        d = self._get(db, context, decision, current=True)
        if decision.decision not in self._decorate(d, context).allowed_actions:
            raise BusinessError("FORBIDDEN_TRANSITION")
        if decision.decision == "approve":
            d.request.status = (
                "additional_approval"
                if context.role == "buyer" and "manager" in d.review.required_approvers
                else "approved"
            )
        elif decision.decision == "reject":
            d.request.status = "rejected"
        else:
            d.request.status = "needs_revision"
        d.history.append(
            ApprovalEvent(
                request_id=d.request.request_id,
                version=d.request.version,
                actor_id=context.actor_id,
                decision=decision.decision,
                reason=decision.reason,
                created_at=datetime.now(timezone.utc),
            )
        )
        self._save(db, d)
        return d.request

    @operation
    def download_document(self, db, context, ref, kind):
        d = self._get(db, context, ref)
        if not d.documents or not d.documents.complete or kind not in d.documents.files:
            raise BusinessError("DOCUMENT_NOT_FOUND")
        return d.documents.files[kind].encode("utf-8")

    @operation
    def save_preferences(self, db, context, values, consent=False):
        if not consent:
            raise BusinessError("CONSENT_REQUIRED")
        if set(values) - {"comparison_priority", "output_style"}:
            raise BusinessError("PREFERENCE_NOT_ALLOWED")
        if values.get("comparison_priority", "price") not in (
            "price",
            "specification",
        ) or values.get("output_style", "concise") not in ("concise", "detailed"):
            raise BusinessError("PREFERENCE_NOT_ALLOWED")
        db.execute(
            "INSERT OR REPLACE INTO preferences VALUES(?,?)", (context.actor_id, json.dumps(values))
        )
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO preference_meta VALUES(?,?,?) ON CONFLICT(actor) DO UPDATE SET updated_at=excluded.updated_at",
            (context.actor_id, now, now),
        )
        return values

    @operation
    def get_preferences(self, db, context):
        row = db.execute(
            "SELECT body FROM preferences WHERE actor=?", (context.actor_id,)
        ).fetchone()
        return json.loads(row[0]) if row else {}
