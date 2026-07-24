import math


def load_inputs(raw):
    if not isinstance(raw, dict):
        raise ValueError("inputs must be an object")
    names = [
        "opening_cash",
        "opening_receivables",
        "opening_inventory",
        "opening_ppe",
        "opening_payables",
        "opening_other_liabilities",
        "opening_term_debt",
        "opening_revolver",
        "opening_equity",
        "paint_units",
        "paint_price",
        "paint_unit_cost",
        "paint_overhead",
        "tools_units",
        "tools_price",
        "tools_unit_cost",
        "tools_storage",
        "corporate_opex",
        "receivable_days",
        "inventory_days",
        "payable_days",
        "opening_ppe_life",
        "new_capex_life",
        "disposal_rate",
        "minimum_cash",
        "mandatory_amortization",
        "debt_interest_rate",
        "cash_interest_rate",
        "cash_sweep_pct",
        "tax_rate",
        "wacc",
        "exit_multiple",
    ]
    operating_drivers = [
        "paint_unit_growth",
        "paint_price_inflation",
        "paint_cost_inflation",
        "paint_overhead_inflation",
        "tools_unit_growth",
        "tools_price_inflation",
        "tools_cost_inflation",
        "tools_storage_inflation",
        "corporate_opex_inflation",
    ]
    flexible_levels = ["capex"]
    result = {}
    for name in names + operating_drivers + flexible_levels:
        if name not in raw:
            raise ValueError("missing required input: " + name)
    for name in names:
        value = raw[name]
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise ValueError("input must be finite number: " + name)
        result[name] = float(value)
    for name in operating_drivers:
        value = raw[name]
        values = (
            [value] * 4
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else value
        )
        if not isinstance(values, list) or len(values) != 4:
            raise ValueError(
                "operating transition input must be a number or four numbers: " + name
            )
        if any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            for x in values
        ):
            raise ValueError("input contains non-finite number: " + name)
        result[name] = [float(x) for x in values]
    for name in flexible_levels:
        value = raw[name]
        values = (
            [value] * 5
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else value
        )
        if not isinstance(values, list) or len(values) != 5:
            raise ValueError(
                "annual level input must be a number or five numbers: " + name
            )
        if any(
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(x)
            for x in values
        ):
            raise ValueError("input contains non-finite number: " + name)
        result[name] = [float(x) for x in values]
    nonnegative = names[:18] + ["minimum_cash", "mandatory_amortization"]
    if any(result[x] < 0 for x in nonnegative) or any(x < 0 for x in result["capex"]):
        raise ValueError("amount inputs must be non-negative")
    for x in operating_drivers:
        if any(v < -0.5 or v > 1 for v in result[x]):
            raise ValueError("growth or inflation must be between -50% and 100%: " + x)
    for x in ["receivable_days", "inventory_days", "payable_days"]:
        if result[x] < 0 or result[x] > 365:
            raise ValueError("days out of bounds: " + x)
    for x in ["opening_ppe_life", "new_capex_life"]:
        if result[x] < 1 or result[x] > 40 or result[x] != int(result[x]):
            raise ValueError("useful life must be integer 1 to 40: " + x)
    bounds = {
        "disposal_rate": (0, 0.25),
        "debt_interest_rate": (0, 0.3),
        "cash_interest_rate": (0, 0.3),
        "cash_sweep_pct": (0, 1),
        "tax_rate": (0, 0.5),
        "wacc": (0, 0.3),
        "exit_multiple": (0, 15),
    }
    for x, pair in bounds.items():
        if result[x] < pair[0] or result[x] > pair[1]:
            raise ValueError("input out of bounds: " + x)
    assets = (
        result["opening_cash"]
        + result["opening_receivables"]
        + result["opening_inventory"]
        + result["opening_ppe"]
    )
    claims = (
        result["opening_payables"]
        + result["opening_other_liabilities"]
        + result["opening_term_debt"]
        + result["opening_revolver"]
        + result["opening_equity"]
    )
    if abs(assets - claims) > 0.01:
        raise ValueError("opening balance sheet does not balance")
    return result
