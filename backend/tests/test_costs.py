from __future__ import annotations

from decimal import Decimal

from scripts.calculate_aws_cost import estimate


def test_on_demand_cost_estimate_is_deterministic() -> None:
    eight_hours = estimate(Decimal(8))
    month = estimate(Decimal(730))

    assert eight_hours["total"].quantize(Decimal("0.0001")) == Decimal("4.2831")
    assert month["compute"] == Decimal("383.980")
    assert month["public_ipv4"] == Decimal("3.650")
    assert month["storage"] == Decimal("3.20")
    assert month["total"] == Decimal("390.830")
