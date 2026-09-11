"""Explicit synthetic fixtures for live-model evaluation, never shipped as catalog."""

from datetime import datetime, timezone

from purchase_agent.schemas import CoupangProduct, ProductEvidence, ProductSupplement


def synthetic_catalog():
    now = datetime.now(timezone.utc)
    return [
        ProductEvidence(
            evidence_id=f"e{i}",
            product=CoupangProduct(
                productId=i,
                productName=f"합성 모니터 {i}",
                productPrice=p,
                productUrl=f"https://www.coupang.com/vp/products/{i}",
                productImage="https://example.com/synthetic.png",
                isRocket=False,
                isFreeShipping=True,
                keyword="모니터",
                rank=i,
            ),
            supplement=ProductSupplement(
                product_id=i,
                item_id=str(i),
                vendor_item_id=str(i),
                option_label="27인치 QHD",
                verified_specs=["27인치", "QHD"],
                shipping_rule="free",
                shipping_source_url=f"https://www.coupang.com/vp/products/{i}",
                source_checked_at=now,
                source_status="verified",
            ),
            query="업무용 모니터 monitor",
            retrieved_at=now,
            fixture_version="synthetic-evaluation-only",
        )
        for i, p in [(1, 280000), (2, 250000)]
    ]
