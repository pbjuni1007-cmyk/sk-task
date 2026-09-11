from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from pydantic import HttpUrl

from purchase_agent.config import demo_context
from purchase_agent.schemas import (
    CoupangProduct,
    DecisionInput,
    ProductEvidence,
    ProductSupplement,
    RequestInput,
    RequestPatch,
    RequestRef,
)
from purchase_agent.workflow import LocalPurchaseService


@pytest.fixture
def catalog():
    return [
        ProductEvidence(
            evidence_id=f"e{i}",
            product=CoupangProduct(
                productId=i,
                productName=f"Synthetic monitor {i}",
                productPrice=p,
                productUrl=f"https://www.coupang.com/vp/products/{i}",
                productImage="https://example.com/test.png",
                isRocket=False,
                isFreeShipping=True,
                keyword="monitor",
                rank=i,
            ),
            supplement=ProductSupplement(
                product_id=i,
                item_id=str(i),
                vendor_item_id=str(i),
                option_label="27 QHD",
                verified_specs=["27 QHD"],
                shipping_rule="free",
                shipping_source_url=f"https://www.coupang.com/vp/products/{i}",
                source_checked_at=datetime.now(timezone.utc),
                source_status="verified",
            ),
            query="monitor",
            retrieved_at=datetime.now(timezone.utc),
            fixture_version="test",
        )
        for i, p in [(1, 280000), (2, 250000)]
    ]


@pytest.fixture
def service(tmp_path, catalog):
    return LocalPurchaseService(tmp_path / "test.db", catalog)


OWNER = demo_context("employee_a", "s")
BUYER = demo_context("buyer_a", "s")
MANAGER = demo_context("manager_a", "s")


def ready(service, quantity=3, budget=900000, purpose="개발 업무"):
    r = service.create_request(
        OWNER, RequestInput(quantity=quantity, budget_krw=budget, purpose=purpose), "create"
    ).data
    assert service.search_products(OWNER, r, "monitor").ok
    r = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, selected_evidence_id="e1")
    ).data
    review = service.review_request(OWNER, r).data
    docs = service.generate_documents(OWNER, r).data
    return r, review, docs


def submit(service, r, docs):
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    result = service.submit_request(OWNER, c)
    assert result.ok, result
    return result.data, c


def test_complete_normal_and_duplicate(service):
    r, review, docs = ready(service)
    assert review.review_total_krw == 840000 and review.can_submit
    assert all("840,000원" in text for text in docs.files.values())
    result, c = submit(service, r, docs)
    duplicate = service.submit_request(OWNER, c).data
    assert duplicate.submitted_at == result.submitted_at
    approved = service.decide(
        BUYER, DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
    )
    assert approved.data.status == "approved"
    assert service.submit_request(OWNER, c).data.status == "approved"
    assert service.generate_documents(OWNER, r).data.bundle_hash == docs.bundle_hash
    assert len(service.get_request(OWNER, r).data.history) == 2


def test_purpose_optional_until_submit(service):
    r, review, docs = ready(service, purpose=None)
    assert not review.can_submit and docs.complete
    assert not service.prepare_submission(OWNER, r, docs.bundle_id).ok
    changed = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, purpose="업무")
    ).data
    assert changed.version == r.version + 1
    assert not service.review_request(OWNER, r).ok


def test_high_amount(service):
    r, review, docs = ready(service, 4, 1200000)
    submit(service, r, docs)
    assert (
        service.decide(
            BUYER, DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
        ).data.status
        == "additional_approval"
    )
    assert (
        service.decide(
            MANAGER, DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
        ).data.status
        == "approved"
    )


def test_unknown_shipping(service):
    service.catalog[0].supplement.source_status = "unverified"
    r, review, docs = ready(service)
    assert review.review_total_krw is None and review.remaining_krw is None
    assert "확인 필요" in docs.files["purchase_request"]
    assert not service.prepare_submission(OWNER, r, docs.bundle_id).ok


def test_ownership_and_nonce_thread(service):
    r, _, docs = ready(service)
    assert not service.get_request(demo_context("employee_b", "s"), r).ok
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    assert not service.submit_request(demo_context("employee_a", "other"), c).ok
    assert not service.decide(
        OWNER, DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
    ).ok


def test_restart_preserves_db_but_invalidates_pending_confirmation(service):
    r, _, docs = ready(service)
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    resumed = LocalPurchaseService(service.db.path)
    assert resumed.get_request(OWNER, r).data.documents == docs
    assert not resumed.submit_request(OWNER, c).ok


def test_concurrent_submission(service):
    r, _, docs = ready(service)
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.submit_request(OWNER, c), range(2)))
    assert all(x.ok for x in results)
    assert len(service.get_request(OWNER, r).data.history) == 1


def test_change_preserves_old_docs(service):
    r, _, docs = ready(service)
    submit(service, r, docs)
    new = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, quantity=4)
    ).data
    assert new.version == r.version + 1 and new.submitted_at is None
    assert service.get_request(OWNER, r).data.documents == docs
    assert service.get_request(OWNER, new).data.documents is None
    assert not service.decide(
        BUYER, DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
    ).ok


def test_price_refresh_creates_version(service):
    r, _, docs = ready(service)
    service.catalog[0].product.productPrice = 290000
    assert service.search_products(OWNER, r, "monitor", refresh=True).ok
    assert not service.review_request(OWNER, r).ok
    new = RequestRef(request_id=r.request_id, version=r.version + 1)
    assert service.review_request(OWNER, new).data.review_total_krw == 870000
    assert service.get_request(OWNER, r).data.documents == docs


def test_preferences(service):
    assert not service.save_preferences(OWNER, {"output_style": "concise"}).ok
    assert service.save_preferences(OWNER, {"output_style": "concise"}, consent=True).ok
    assert (
        service.get_preferences(demo_context("employee_a", "next")).data["output_style"]
        == "concise"
    )
    assert service.get_preferences(demo_context("employee_b", "s")).data == {}


@pytest.mark.parametrize(
    "price,quantity,fee,rule,total",
    [(249000, 2, 3000, "per_order", 501000), (249000, 4, 1000, "per_item", 1000000)],
)
def test_shipping_boundaries(service, price, quantity, fee, rule, total):
    service.catalog[0].product.productPrice = price
    service.catalog[0].supplement.shipping_rule = rule
    service.catalog[0].supplement.fee_krw = fee
    r, review, _ = ready(service, quantity, 1100000)
    assert review.review_total_krw == total


@pytest.mark.parametrize("total,expected", [(499999, True), (500000, False)])
def test_comparison_threshold(service, total, expected):
    service.catalog = service.catalog[:1]
    service.catalog[0].product.productPrice = total
    _, review, _ = ready(service, 1, 600000)
    assert review.can_submit == expected


def test_render_failure_rollback(service, monkeypatch):
    r = service.create_request(
        OWNER, RequestInput(quantity=3, budget_krw=900000, purpose="업무"), "a"
    ).data
    service.search_products(OWNER, r, "monitor")
    r = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, selected_evidence_id="e1")
    ).data
    service.review_request(OWNER, r)

    def fail(_):
        raise ValueError("RENDER_FAILED")

    monkeypatch.setattr("purchase_agent.documents.render", fail)
    assert not service.generate_documents(OWNER, r).ok
    d = service.get_request(OWNER, r).data
    assert d.documents is None and d.request.status == "draft"


def test_forged_profile_rejected(service):
    r, _, _ = ready(service)
    forged = OWNER.model_copy(update={"role": "buyer"})
    assert service.get_request(forged, r).error_code == "INVALID_CONTEXT"


def test_document_tamper_blocks_submit(service):
    r, _, docs = ready(service)
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    with service.db.transaction() as db:
        d = service._get(db, OWNER, r)
        d.documents.files["review"] = "tampered"
        service._save(db, d)
    assert service.submit_request(OWNER, c).error_code == "DOCUMENT_MISMATCH"


def test_repeat_review_preserves_ready_documents(service):
    r, review, docs = ready(service)
    before = service.get_request(OWNER, r).data

    repeated = service.review_request(OWNER, r)

    assert repeated.ok and repeated.data == review
    after = service.get_request(OWNER, r).data
    assert after.request.status == "ready"
    assert after.request.version == before.request.version
    assert after.documents == before.documents == docs
    assert after.documents.bundle_id == docs.bundle_id
    assert after.documents.bundle_hash == docs.bundle_hash


def test_policy_change_creates_version(service, monkeypatch):
    r, _, docs = ready(service)
    monkeypatch.setattr("purchase_agent.policy.POLICY_VERSION", "purchase-v3-test")
    new_review = service.review_request(OWNER, r).data
    assert new_review.version == r.version + 1
    old = service.get_request(OWNER, r).data
    assert old.request.version == r.version and old.request.status == "ready"
    assert old.documents == docs
    new = service.get_latest_request(OWNER, r.request_id).data
    assert new.request.version == r.version + 1 and new.request.status == "draft"
    assert new.review == new_review and new.review.policy_version == "purchase-v3-test"
    assert new.documents is None


def test_revision_must_not_overwrite_submitted_documents(service):
    r, _, docs = ready(service)
    submit(service, r, docs)
    assert service.decide(
        BUYER,
        DecisionInput(
            request_id=r.request_id,
            version=r.version,
            decision="request_revision",
            reason="목적 구체화",
        ),
    ).ok
    assert service.generate_documents(OWNER, r).data == docs
    new = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, purpose="개발팀 온보딩 업무")
    ).data
    assert new.version == r.version + 1 and new.status == "draft"


def test_negative_spec_is_not_positive_match(service):
    for e in service.catalog:
        e.supplement.verified_specs = ["USB-C 미지원"]
    r = service.create_request(
        OWNER,
        RequestInput(quantity=2, budget_krw=600000, purpose="업무", requirements=["USB-C"]),
        "spec",
    ).data
    service.search_products(OWNER, r, "monitor")
    r = service.update_request(
        OWNER, r.request_id, RequestPatch(expected_version=r.version, selected_evidence_id="e1")
    ).data
    result = service.review_request(OWNER, r).data
    assert not result.can_submit
    assert next(c for c in result.checks if c.policy_id == "SPEC").result != "pass"


def test_limit_expansion_does_not_reuse_truncated_cache(service):
    r = service.create_request(OWNER, RequestInput(quantity=1, budget_krw=500000), "limit").data
    assert len(service.search_products(OWNER, r, "monitor", limit=1).data) == 1
    assert len(service.search_products(OWNER, r, "monitor", limit=2).data) == 2
    r = service.get_latest_request(OWNER, r.request_id).data.request
    attempts = sum(c.attempts for c in service._search_clients.values())
    assert len(service.search_products(OWNER, r, "monitor", limit=2).data) == 2
    assert sum(c.attempts for c in service._search_clients.values()) == attempts


def test_concurrent_approval_changes_state_once(service):
    r, _, docs = ready(service)
    submit(service, r, docs)
    decision = DecisionInput(request_id=r.request_id, version=r.version, decision="approve")
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: service.decide(BUYER, decision), range(2)))
    assert sum(x.ok for x in results) == 1
    assert len(service.get_request(OWNER, r).data.history) == 2


def test_shipping_only_change_creates_new_version(service):
    r, _, docs = ready(service)
    service.catalog[0].supplement.shipping_rule = "per_order"
    service.catalog[0].supplement.fee_krw = 3000
    assert service.search_products(OWNER, r, "monitor", refresh=True).ok
    latest = service.get_latest_request(OWNER, r.request_id).data.request
    assert latest.version == r.version + 1
    assert service.review_request(OWNER, latest).data.review_total_krw == 843000
    assert service.get_request(OWNER, r).data.documents == docs


def test_submit_revision_race_is_serialized(service):
    r, _, docs = ready(service)
    c = service.prepare_submission(OWNER, r, docs.bundle_id).data
    with ThreadPoolExecutor(2) as pool:
        submit_future = pool.submit(service.submit_request, OWNER, c)
        update_future = pool.submit(
            service.update_request,
            OWNER,
            r.request_id,
            RequestPatch(expected_version=r.version, quantity=4),
        )
        submitted, updated = submit_future.result(), update_future.result()
    assert updated.ok
    latest = service.get_latest_request(OWNER, r.request_id).data
    assert latest.request.version == r.version + 1 and latest.request.submitted_at is None
    old = service.get_request(OWNER, r).data
    assert len(old.history) == (1 if submitted.ok else 0)


def test_same_product_different_option_respects_wire_limit(service):
    first = service.catalog[0]
    other = first.model_copy(deep=True)
    other.evidence_id = "other"
    other.product.productPrice = 400000
    other.product.productUrl = HttpUrl("https://www.coupang.com/vp/products/1?itemId=other")
    other.supplement.item_id = "other"
    other.supplement.option_label = "32 QHD"
    service.catalog = [first, other]
    r = service.create_request(OWNER, RequestInput(quantity=1, budget_krw=900000), "options").data
    one = service.search_products(OWNER, r, "monitor", limit=1).data
    assert len(one) == 1 and one[0].supplement.item_id == first.supplement.item_id
    assert one[0].product.productPrice == 280000
    both = service.search_products(OWNER, r, "monitor", limit=2).data
    assert [(e.evidence_id, e.product.productPrice) for e in both] == [
        ("e1", 280000),
        ("other", 400000),
    ]
