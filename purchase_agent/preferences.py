"""One presentation order for tools, structured responses, and candidate UI."""

from .policy import eligible, shipping_total


def order_candidates(candidates, preferences, inputs):
    priority = preferences.get("comparison_priority")
    if priority == "price":

        def key(e):
            fee = shipping_total(e.supplement, inputs.quantity)
            return float("inf") if fee is None else e.product.productPrice * inputs.quantity + fee

        return sorted(candidates, key=key)
    if priority == "specification":
        return sorted(
            candidates, key=lambda e: not eligible(e, inputs.requirements, inputs.quantity)
        )
    return list(candidates)
