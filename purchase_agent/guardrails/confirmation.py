"""제출 동의의 결속·만료·문서 무결성 검사. 토큰 발급·소비는 DB 트랜잭션 안에서 수행한다."""

import hashlib
import json

from .. import documents, policy
from ..errors import BusinessError


def validate_ready(d, bundle_id):
    if (
        d.request.status != "ready"
        or not d.review
        or not d.review.can_submit
        or not d.documents
        or not d.documents.complete
        or d.documents.bundle_id != bundle_id
    ):
        raise BusinessError("NOT_READY")


def validate_binding(c, context, confirmation):
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


def validate_fresh_token(c, boot):
    if c["boot"] != boot or c["consumed"]:
        raise BusinessError("CONFIRMATION_EXPIRED")


def validate_submission(d, c):
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
