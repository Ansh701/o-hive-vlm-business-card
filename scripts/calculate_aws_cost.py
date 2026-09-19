from __future__ import annotations

import argparse
from decimal import ROUND_HALF_UP, Decimal

ON_DEMAND_COMPUTE_PER_HOUR = Decimal("0.526")
PUBLIC_IPV4_PER_HOUR = Decimal("0.005")
GP3_PER_GB_MONTH = Decimal("0.08")
GP3_SIZE_GB = Decimal(40)
HOURS_PER_MONTH = Decimal(730)


def estimate(hours: Decimal) -> dict[str, Decimal]:
    compute = ON_DEMAND_COMPUTE_PER_HOUR * hours
    public_ipv4 = PUBLIC_IPV4_PER_HOUR * hours
    storage = GP3_PER_GB_MONTH * GP3_SIZE_GB * hours / HOURS_PER_MONTH
    return {
        "compute": compute,
        "public_ipv4": public_ipv4,
        "storage": storage,
        "total": compute + public_ipv4 + storage,
    }


def money(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic us-east-1 on-demand cost estimate for the AWS Qwen host."
    )
    parser.add_argument("--hours", type=Decimal, default=Decimal(8))
    arguments = parser.parse_args()
    result = estimate(arguments.hours)
    print(f"hours={arguments.hours}")
    for category, value in result.items():
        print(f"{category}_usd={money(value)}")


if __name__ == "__main__":
    main()
