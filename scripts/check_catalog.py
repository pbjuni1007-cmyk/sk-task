import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from purchase_agent.catalog import load_catalog
from purchase_agent.policy import shipping_total

parser = argparse.ArgumentParser()
parser.add_argument("--strict", action="store_true")
args = parser.parse_args()
try:
    catalog = load_catalog()
    valid = [
        e
        for e in catalog
        if shipping_total(e.supplement, 1) is not None
        and e.product.productUrl.host in ("www.coupang.com", "coupang.com")
    ]
    print(f"catalog={len(catalog)}, verified={len(valid)}")
    if args.strict and len({e.product.productId for e in valid}) < 2:
        print("BLOCKED: 실제 상품2개 및 옵션·판매자·배송비 근거 필요")
        sys.exit(1)
except (ValueError, OSError) as e:
    print(type(e).__name__)
    sys.exit(1)
