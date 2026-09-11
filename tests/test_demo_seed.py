from collections import Counter

import pytest

from purchase_agent.config import demo_context
from purchase_agent.schemas import ListQuery
from purchase_agent.workflow import LocalPurchaseService
from scripts.seed_demo import seed


def test_company_scenarios_and_isolation(tmp_path):
    path = tmp_path / "company.sqlite3"
    seed(path)
    service = LocalPurchaseService(path)
    buyer = demo_context("buyer_a", "test")
    items = [
        d
        for actor in ("employee_a", "employee_b")
        for d in service.list_requests(
            demo_context(actor, "test"), ListQuery(folder="mine")
        ).data.items
    ]
    assert Counter(d.request.status for d in items) == {
        "approved": 3,
        "rejected": 1,
        "needs_revision": 1,
        "additional_approval": 1,
        "submitted": 2,
        "ready": 1,
        "draft": 1,
    }
    for detail in items:
        if detail.request.status != "draft":
            assert detail.documents.complete and len(detail.documents.files) == 3
            assert detail.review.can_submit
        if detail.request.submitted_at:
            assert detail.history[0].decision == "submit"
    assert service.list_requests(buyer, ListQuery(folder="pending")).data.total == 2
    manager = demo_context("manager_a", "test")
    assert service.list_requests(manager, ListQuery(folder="pending")).data.total == 1
    owner = demo_context("employee_b", "test")
    mine = service.list_requests(owner, ListQuery(folder="mine")).data
    assert mine.total == 4 and all(d.request.owner_id == "employee_b" for d in mine.items)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        seed(path)
    assert path.read_bytes() == before


def test_empty_practice_database(tmp_path):
    path = tmp_path / "empty.sqlite3"
    assert seed(path, empty=True) == []
    service = LocalPurchaseService(path)
    assert (
        service.list_requests(
            demo_context("buyer_a", "test"), ListQuery(folder="pending")
        ).data.total
        == 0
    )
