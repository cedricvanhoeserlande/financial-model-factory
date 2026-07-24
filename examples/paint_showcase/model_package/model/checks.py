import math
from model.assumptions import load_inputs
from model.schedules import run_all
from model.schedules.core import convergence_status


def run_checks(inputs, outputs):
    tolerance = 0.02
    data = next(
        block["data"]
        for block in outputs["output_blocks"]
        if block["id"] == "financial_model"
    )

    def result(identifier, passed, message, evidence, status="passed"):
        return {
            "id": identifier,
            "passed": bool(passed),
            "status": status,
            "message": message,
            "evidence": evidence,
        }

    def clone(source, changes=None):
        copied = {
            key: list(value) if isinstance(value, list) else value
            for key, value in source.items()
        }
        if changes:
            copied.update(changes)
        return copied

    def schedule(raw):
        return run_all(load_inputs(raw))

    def transition(name, index):
        value = inputs[name]
        return value[index] if isinstance(value, list) else value

    def finite(value):
        if isinstance(value, dict):
            return all(finite(item) for item in value.values())
        if isinstance(value, list):
            return all(finite(item) for item in value)
        return not isinstance(value, float) or math.isfinite(value)

    def accepted(raw):
        try:
            load_inputs(raw)
            return True
        except ValueError:
            return False

    def rejected(raw):
        return not accepted(raw)

    def balanced(changes):
        raw = clone(inputs, changes)
        assets = (
            raw["opening_cash"]
            + raw["opening_receivables"]
            + raw["opening_inventory"]
            + raw["opening_ppe"]
        )
        claims_without_equity = (
            raw["opening_payables"]
            + raw["opening_other_liabilities"]
            + raw["opening_term_debt"]
            + raw["opening_revolver"]
        )
        raw["opening_equity"] = assets - claims_without_equity
        return raw

    scalar_bounds = {
        "receivable_days": (0.0, 365.0),
        "inventory_days": (0.0, 365.0),
        "payable_days": (0.0, 365.0),
        "opening_ppe_life": (1.0, 40.0),
        "new_capex_life": (1.0, 40.0),
        "disposal_rate": (0.0, 0.25),
        "debt_interest_rate": (0.0, 0.3),
        "cash_interest_rate": (0.0, 0.3),
        "cash_sweep_pct": (0.0, 1.0),
        "tax_rate": (0.0, 0.5),
        "wacc": (0.0, 0.3),
        "exit_multiple": (0.0, 15.0),
    }
    amount_names = [
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
        "minimum_cash",
        "mandatory_amortization",
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
    level_drivers = ["capex"]
    validation_evidence = {}
    legal_zero_opening = balanced(
        {
            "opening_cash": 0.0,
            "opening_receivables": 0.0,
            "opening_inventory": 0.0,
            "opening_ppe": 0.0,
            "opening_payables": 0.0,
            "opening_other_liabilities": 0.0,
            "opening_term_debt": 0.0,
            "opening_revolver": 0.0,
            "opening_equity": 0.0,
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 0.0,
            "minimum_cash": 0.0,
            "mandatory_amortization": 0.0,
        }
    )
    for name in amount_names:
        zero_ok = (
            accepted(legal_zero_opening)
            if name.startswith("opening_")
            else accepted(balanced({name: 0.0}))
        )
        negative_raw = (
            clone(inputs, {name: -1.0})
            if name == "opening_equity"
            else balanced({name: -1.0})
        )
        validation_evidence[name] = {
            "zero_accepted": zero_ok,
            "negative_rejected": rejected(negative_raw),
            "nan_rejected": rejected(clone(inputs, {name: float("nan")})),
            "infinity_rejected": rejected(clone(inputs, {name: float("inf")})),
        }
    for name, pair in scalar_bounds.items():
        low, high = pair
        validation_evidence[name] = {
            "lower_accepted": accepted(clone(inputs, {name: low})),
            "upper_accepted": accepted(clone(inputs, {name: high})),
            "below_rejected": rejected(clone(inputs, {name: low - 0.01})),
            "above_rejected": rejected(clone(inputs, {name: high + 0.01})),
            "nan_rejected": rejected(clone(inputs, {name: float("nan")})),
            "infinity_rejected": rejected(clone(inputs, {name: float("inf")})),
        }
    validation_evidence["useful_life_fractional_rejected"] = rejected(
        clone(inputs, {"opening_ppe_life": 1.5})
    ) and rejected(clone(inputs, {"new_capex_life": 1.5}))
    flexible_evidence = {}
    flexible_passed = True
    for name in operating_drivers + level_drivers:
        is_level = name in level_drivers
        count = 5 if is_level else 4
        lo, hi = (0.0, 1000.0) if is_level else (-0.5, 1.0)
        scalar_ok = accepted(clone(inputs, {name: lo}))
        array_ok = accepted(clone(inputs, {name: [lo] * count}))
        length_bad = rejected(clone(inputs, {name: [lo] * (count - 1)}))
        nonfinite_positions = []
        for position in range(count):
            for nonfinite_type, nonfinite_value in [
                ("nan", float("nan")),
                ("positive_infinity", float("inf")),
                ("negative_infinity", float("-inf")),
            ]:
                invalid_member = [lo] * count
                invalid_member[position] = nonfinite_value
                nonfinite_positions.append(
                    {
                        "position": position + 1,
                        "period_label": (
                            ("Y" + str(position + 1))
                            if is_level
                            else ("FY" + str(position + 2))
                        ),
                        "nonfinite_type": nonfinite_type,
                        "rejected": rejected(clone(inputs, {name: invalid_member})),
                    }
                )
        nonfinite_bad = all(item["rejected"] for item in nonfinite_positions)
        positions = []
        scalar_economic_results = []
        try:
            baseline = schedule(clone(inputs, {name: [lo] * count}))
            for position in range(count):
                candidate = [lo] * count
                candidate[position] = hi
                changed = schedule(clone(inputs, {name: candidate}))
                target = position if is_level else position + 1
                if is_level:
                    depreciation_baseline = baseline["ppe"][target]["depreciation"]
                    depreciation_changed = changed["ppe"][target]["depreciation"]
                    fcff_baseline = baseline["fcff"][target]["fcff"]
                    fcff_changed = changed["fcff"][target]["fcff"]
                    downstream = [
                        {
                            "output_path": "output_blocks.3.data.ppe."
                            + str(target)
                            + ".depreciation",
                            "period": baseline["ppe"][target]["year"],
                            "baseline_value": depreciation_baseline,
                            "changed_value": depreciation_changed,
                            "economic_result_changed": abs(
                                depreciation_changed - depreciation_baseline
                            )
                            > tolerance,
                        },
                        {
                            "output_path": "output_blocks.3.data.fcff."
                            + str(target)
                            + ".fcff",
                            "period": baseline["fcff"][target]["year"],
                            "baseline_value": fcff_baseline,
                            "changed_value": fcff_changed,
                            "economic_result_changed": abs(fcff_changed - fcff_baseline)
                            > tolerance,
                        },
                    ]
                    moved = any(item["economic_result_changed"] for item in downstream)
                    positions.append(
                        {
                            "position": position + 1,
                            "period": baseline["ppe"][target]["year"],
                            "baseline_capex_control": [lo] * count,
                            "changed_capex_control": candidate,
                            "downstream_economic_results": downstream,
                            "downstream_economic_result_changed": moved,
                        }
                    )
                else:
                    moved = (
                        abs(
                            changed["operations"][target]["revenue"]
                            - baseline["operations"][target]["revenue"]
                        )
                        > tolerance
                        or abs(
                            changed["operations"][target]["ebitda"]
                            - baseline["operations"][target]["ebitda"]
                        )
                        > tolerance
                    )
                    positions.append(
                        {
                            "position": position + 1,
                            "transition_label": "FY" + str(target + 1),
                            "output_period": target + 1,
                            "output_moved": moved,
                        }
                    )
            if is_level:
                scalar_baseline = schedule(clone(inputs, {name: lo}))
                scalar_changed = schedule(clone(inputs, {name: hi}))
                for target in range(count):
                    downstream = [
                        {
                            "output_path": "output_blocks.3.data.ppe."
                            + str(target)
                            + ".depreciation",
                            "period": scalar_baseline["ppe"][target]["year"],
                            "baseline_value": scalar_baseline["ppe"][target][
                                "depreciation"
                            ],
                            "changed_value": scalar_changed["ppe"][target][
                                "depreciation"
                            ],
                            "economic_result_changed": abs(
                                scalar_changed["ppe"][target]["depreciation"]
                                - scalar_baseline["ppe"][target]["depreciation"]
                            )
                            > tolerance,
                        },
                        {
                            "output_path": "output_blocks.3.data.fcff."
                            + str(target)
                            + ".fcff",
                            "period": scalar_baseline["fcff"][target]["year"],
                            "baseline_value": scalar_baseline["fcff"][target]["fcff"],
                            "changed_value": scalar_changed["fcff"][target]["fcff"],
                            "economic_result_changed": abs(
                                scalar_changed["fcff"][target]["fcff"]
                                - scalar_baseline["fcff"][target]["fcff"]
                            )
                            > tolerance,
                        },
                    ]
                    scalar_economic_results.append(
                        {
                            "replicated_capex_period": scalar_baseline["ppe"][target][
                                "year"
                            ],
                            "baseline_capex_control": lo,
                            "changed_capex_control": hi,
                            "downstream_economic_results": downstream,
                            "downstream_economic_result_changed": any(
                                item["economic_result_changed"] for item in downstream
                            ),
                        }
                    )
        except ValueError:
            positions = [
                {
                    "position": index + 1,
                    "output_period": index + 1,
                    "output_moved": False,
                }
                for index in range(count)
            ]
            scalar_economic_results = (
                [
                    {
                        "replicated_capex_period": "Y" + str(index + 1),
                        "downstream_economic_results": [],
                        "downstream_economic_result_changed": False,
                    }
                    for index in range(count)
                ]
                if is_level
                else []
            )
        capex_economic_passed = (not is_level) or (
            all(item["downstream_economic_result_changed"] for item in positions)
            and all(
                item["downstream_economic_result_changed"]
                for item in scalar_economic_results
            )
        )
        flexible_evidence[name] = {
            "scalar_replication_accepted": scalar_ok,
            "array_accepted": array_ok,
            "invalid_length_rejected": length_bad,
            "nonfinite_member_rejected": nonfinite_bad,
            "nonfinite_member_probes": nonfinite_positions,
            "position_probes": positions,
            "scalar_downstream_economic_results": scalar_economic_results,
            "capex_downstream_economic_results_passed": capex_economic_passed,
            "timing": "annual_level" if is_level else "FY1_to_FY5_transition",
        }
        flexible_passed = (
            flexible_passed
            and scalar_ok
            and array_ok
            and length_bad
            and nonfinite_bad
            and capex_economic_passed
            and all(
                (
                    item.get("downstream_economic_result_changed")
                    if is_level
                    else item["output_moved"]
                )
                for item in positions
            )
        )
    validation_passed = (
        all(
            all(value.values())
            for value in validation_evidence.values()
            if isinstance(value, dict)
        )
        and validation_evidence["useful_life_fractional_rejected"]
        and flexible_passed
    )

    opening_assets = (
        inputs["opening_cash"]
        + inputs["opening_receivables"]
        + inputs["opening_inventory"]
        + inputs["opening_ppe"]
    )
    opening_claims = (
        inputs["opening_payables"]
        + inputs["opening_other_liabilities"]
        + inputs["opening_term_debt"]
        + inputs["opening_revolver"]
        + inputs["opening_equity"]
    )
    alternative = balanced(
        {
            "opening_cash": inputs["opening_cash"] + 123456.0,
            "opening_ppe": inputs["opening_ppe"] + 654321.0,
            "opening_term_debt": inputs["opening_term_debt"] + 111111.0,
        }
    )
    alternative_ok = accepted(alternative)
    unbalanced_rejected = rejected(
        clone(inputs, {"opening_cash": inputs["opening_cash"] + 1.0})
    )

    ops, wc, ppe, financing = (
        data["operations"],
        data["working_capital"],
        data["ppe"],
        data["financing"],
    )
    bs, cf, income, retained, valuation = (
        data["balance_sheet"],
        data["cash_flow"],
        data["income_statement"],
        data["retained_earnings"],
        data["valuation"],
    )
    segment_residuals = []
    segment_evidence = []
    for i in range(5):
        paint, tools = data["paint"][i], data["tools"][i]
        paint_variable_residual = (
            paint["variable_cost"] - paint["units"] * paint["unit_cost"]
        )
        tools_purchase_residual = (
            tools["purchase_cost"] - tools["units"] * tools["unit_cost"]
        )
        paint_gross_residual = paint["gross_profit"] - (
            paint["revenue"] - paint["variable_cost"] - paint["overhead"]
        )
        tools_gross_residual = tools["gross_profit"] - (
            tools["revenue"] - tools["purchase_cost"] - tools["storage"]
        )
        paint_margin_expected = (
            None if paint["revenue"] == 0 else paint["gross_profit"] / paint["revenue"]
        )
        tools_margin_expected = (
            None if tools["revenue"] == 0 else tools["gross_profit"] / tools["revenue"]
        )
        consolidated_gross_margin_expected = (
            None
            if ops[i]["revenue"] == 0
            else ops[i]["gross_profit"] / ops[i]["revenue"]
        )
        ebitda_margin_expected = (
            None if ops[i]["revenue"] == 0 else ops[i]["ebitda"] / ops[i]["revenue"]
        )
        expected_paint_overhead = inputs["paint_overhead"]
        expected_tools_storage = inputs["tools_storage"]
        for transition_index in range(i):
            expected_paint_overhead *= 1 + transition(
                "paint_overhead_inflation", transition_index
            )
            expected_tools_storage *= 1 + transition(
                "tools_storage_inflation", transition_index
            )
        residuals = {
            "paint_revenue": paint["revenue"] - paint["units"] * paint["price"],
            "tools_revenue": tools["revenue"] - tools["units"] * tools["price"],
            "paint_variable_cost": paint_variable_residual,
            "tools_purchase_cost": tools_purchase_residual,
            "paint_fixed_direct_expense": paint["overhead"] - expected_paint_overhead,
            "tools_fixed_direct_expense": tools["storage"] - expected_tools_storage,
            "paint_gross_profit": paint_gross_residual,
            "tools_gross_profit": tools_gross_residual,
            "paint_gross_margin": (
                0.0
                if paint_margin_expected is None and paint["gross_margin"] is None
                else (
                    paint["gross_margin"] - paint_margin_expected
                    if paint_margin_expected is not None
                    and paint["gross_margin"] is not None
                    else float("inf")
                )
            ),
            "tools_gross_margin": (
                0.0
                if tools_margin_expected is None and tools["gross_margin"] is None
                else (
                    tools["gross_margin"] - tools_margin_expected
                    if tools_margin_expected is not None
                    and tools["gross_margin"] is not None
                    else float("inf")
                )
            ),
            "consolidated_revenue": ops[i]["revenue"]
            - paint["revenue"]
            - tools["revenue"],
            "consolidated_cost_of_sales": ops[i]["cost_of_sales"]
            - paint["variable_cost"]
            - paint["overhead"]
            - tools["purchase_cost"]
            - tools["storage"],
            "consolidated_gross_profit": ops[i]["gross_profit"]
            - paint["gross_profit"]
            - tools["gross_profit"],
            "consolidated_gross_margin": (
                0.0
                if consolidated_gross_margin_expected is None
                and ops[i].get("gross_margin") is None
                else (
                    ops[i].get("gross_margin") - consolidated_gross_margin_expected
                    if consolidated_gross_margin_expected is not None
                    and ops[i].get("gross_margin") is not None
                    else float("inf")
                )
            ),
            "paint_revenue_per_unit": (
                0.0
                if paint["units"] == 0 and paint.get("revenue_per_unit") is None
                else (
                    paint.get("revenue_per_unit") - paint["revenue"] / paint["units"]
                    if paint["units"] != 0 and paint.get("revenue_per_unit") is not None
                    else float("inf")
                )
            ),
            "tools_revenue_per_unit": (
                0.0
                if tools["units"] == 0 and tools.get("revenue_per_unit") is None
                else (
                    tools.get("revenue_per_unit") - tools["revenue"] / tools["units"]
                    if tools["units"] != 0 and tools.get("revenue_per_unit") is not None
                    else float("inf")
                )
            ),
            "ebitda": ops[i]["ebitda"]
            - ops[i]["gross_profit"]
            + ops[i]["corporate_opex"],
            "ebitda_margin": (
                0.0
                if ebitda_margin_expected is None and ops[i]["ebitda_margin"] is None
                else (
                    ops[i]["ebitda_margin"] - ebitda_margin_expected
                    if ebitda_margin_expected is not None
                    and ops[i]["ebitda_margin"] is not None
                    else float("inf")
                )
            ),
        }
        segment_residuals.append(max(abs(value) for value in residuals.values()))
        segment_evidence.append(
            {
                "year": data["periods"][i],
                "residuals": residuals,
                "paint_margin": paint["gross_margin"],
                "tools_margin": tools["gross_margin"],
                "ebitda_margin": ops[i]["ebitda_margin"],
            }
        )
    zero_units_schedule = schedule(
        balanced(
            {
                "paint_units": 0.0,
                "tools_units": 0.0,
                "paint_overhead": 0.0,
                "tools_storage": 0.0,
                "corporate_opex": 0.0,
            }
        )
    )
    zero_price_schedule = schedule(
        balanced(
            {
                "paint_price": 0.0,
                "tools_price": 0.0,
                "paint_overhead": 0.0,
                "tools_storage": 0.0,
                "corporate_opex": 0.0,
            }
        )
    )
    zero_segment_evidence = {}
    for label, fixture in [
        ("zero_units", zero_units_schedule),
        ("zero_price", zero_price_schedule),
    ]:
        zero_segment_evidence[label] = {
            "finite": finite(fixture),
            "paint_revenue": fixture["paint"][0]["revenue"],
            "tools_revenue": fixture["tools"][0]["revenue"],
            "paint_gross_margin": fixture["paint"][0]["gross_margin"],
            "tools_gross_margin": fixture["tools"][0]["gross_margin"],
            "ebitda_margin": fixture["operations"][0]["ebitda_margin"],
        }
    zero_segment_ok = all(
        item["finite"]
        and item["paint_revenue"] == 0.0
        and item["tools_revenue"] == 0.0
        and item["paint_gross_margin"] is None
        and item["tools_gross_margin"] is None
        and item["ebitda_margin"] is None
        for item in zero_segment_evidence.values()
    )
    opening_revenue = (
        inputs["paint_units"] * inputs["paint_price"]
        + inputs["tools_units"] * inputs["tools_price"]
    )
    opening_cos = (
        inputs["paint_units"] * inputs["paint_unit_cost"]
        + inputs["paint_overhead"]
        + inputs["tools_units"] * inputs["tools_unit_cost"]
        + inputs["tools_storage"]
    )
    normalized = (
        opening_revenue * inputs["receivable_days"] / 365
        + opening_cos * inputs["inventory_days"] / 365
        - opening_cos * inputs["payable_days"] / 365
    )
    wc_residuals = []
    for i, row in enumerate(wc):
        prior = normalized if i == 0 else wc[i - 1]["nwc"]
        expected_normalization = (
            inputs["opening_receivables"]
            + inputs["opening_inventory"]
            - inputs["opening_payables"]
            - normalized
            if i == 0
            else 0.0
        )
        wc_residuals.append(
            max(
                abs(
                    row["nwc"] - row["receivables"] - row["inventory"] + row["payables"]
                ),
                abs(row["recurring_cash_flow"] - (prior - row["nwc"])),
                abs(row["normalization_cash_flow"] - expected_normalization),
            )
        )
    zero_days_schedule = schedule(
        clone(
            inputs, {"receivable_days": 0.0, "inventory_days": 0.0, "payable_days": 0.0}
        )
    )
    full_days_schedule = schedule(
        clone(
            inputs,
            {"receivable_days": 365.0, "inventory_days": 365.0, "payable_days": 365.0},
        )
    )
    zero_days_rows = zero_days_schedule["working_capital"]
    full_days_rows = full_days_schedule["working_capital"]
    zero_days_ok = zero_days_schedule["opening_working_capital"][
        "normalized_nwc"
    ] == 0.0 and all(
        row["receivables"] == 0.0 and row["inventory"] == 0.0 and row["payables"] == 0.0
        for row in zero_days_rows
    )
    full_days_residuals = []
    for index, row in enumerate(full_days_rows):
        full_ops = full_days_schedule["operations"][index]
        full_days_residuals.extend(
            [
                row["receivables"] - full_ops["revenue"],
                row["inventory"] - full_ops["cost_of_sales"],
                row["payables"] - full_ops["cost_of_sales"],
            ]
        )
    full_days_ok = (
        abs(
            full_days_schedule["opening_working_capital"]["normalized_nwc"]
            - (opening_revenue)
        )
        <= tolerance
        and max(abs(value) for value in full_days_residuals) <= tolerance
    )
    wc_boundary_evidence = {
        "zero_days": {
            "finite": finite(zero_days_schedule),
            "normalized_opening_nwc": zero_days_schedule["opening_working_capital"][
                "normalized_nwc"
            ],
            "forecast_balances": [
                {
                    "year": row["year"],
                    "receivables": row["receivables"],
                    "inventory": row["inventory"],
                    "payables": row["payables"],
                }
                for row in zero_days_rows
            ],
        },
        "full_days": {
            "finite": finite(full_days_schedule),
            "normalized_opening_receivables": opening_revenue,
            "normalized_opening_inventory": opening_cos,
            "normalized_opening_payables": opening_cos,
            "normalized_opening_nwc": full_days_schedule["opening_working_capital"][
                "normalized_nwc"
            ],
            "forecast_activity_base_residuals": full_days_residuals,
        },
    }

    (
        ppe_residuals,
        depreciation_residuals,
        retirement_residuals,
        retirement_eligibility,
        depreciation_evidence,
    ) = ([], [], [], [], [])
    for row_index, row in enumerate(ppe):
        ppe_residuals.append(
            abs(
                row["closing_net_ppe"]
                - sum(pool["closing_net"] for pool in row["pools"])
            )
        )
        for pool in row["pools"]:
            ppe_residuals.append(
                abs(pool["closing_net"] - (pool["opening_net"] - pool["depreciation"]))
            )
            if pool["id"] == "opening":
                expected_depreciation = min(
                    pool["opening_net"],
                    inputs["opening_ppe"] / inputs["opening_ppe_life"],
                )
                convention = "full_year_opening_pool"
            else:
                entry_index = int(pool["id"].split("_")[1]) - 1
                capex_values = (
                    inputs["capex"]
                    if isinstance(inputs["capex"], list)
                    else [inputs["capex"]] * 5
                )
                annual_charge = capex_values[entry_index] / inputs["new_capex_life"]
                expected_depreciation = min(
                    pool["opening_net"],
                    annual_charge * (0.5 if row_index == entry_index else 1.0),
                )
                convention = (
                    "half_year_entry"
                    if row_index == entry_index
                    else "full_year_or_final_cap"
                )
            depreciation_residuals.append(
                abs(pool["depreciation"] - expected_depreciation)
            )
            depreciation_evidence.append(
                {
                    "year": row["year"],
                    "pool": pool["id"],
                    "convention": convention,
                    "expected_depreciation": expected_depreciation,
                    "actual_depreciation": pool["depreciation"],
                    "residual": pool["depreciation"] - expected_depreciation,
                }
            )
            retirement_residuals.append(
                abs(
                    pool["retirement_gross_cost"]
                    - pool["retirement_accumulated_depreciation"]
                )
            )
            retirement_eligibility.append(
                pool["retirement_gross_cost"]
                <= pool["fully_depreciated_retirement_availability"] + tolerance
                and (
                    pool["retirement_gross_cost"] <= tolerance
                    or abs(pool["pre_retirement_net_book_value"]) <= tolerance
                )
            )
    retirement_fixture = balanced(
        {
            "opening_cash": 0.0,
            "opening_receivables": 0.0,
            "opening_inventory": 0.0,
            "opening_ppe": 1000.0,
            "opening_payables": 0.0,
            "opening_other_liabilities": 0.0,
            "opening_term_debt": 0.0,
            "opening_revolver": 0.0,
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 0.0,
            "capex": 0.0,
            "opening_ppe_life": 1.0,
            "new_capex_life": 1.0,
            "minimum_cash": 0.0,
            "mandatory_amortization": 0.0,
            "disposal_rate": 0.25,
        }
    )
    zero_retirement = schedule(clone(retirement_fixture, {"disposal_rate": 0.0}))
    positive_retirement = schedule(retirement_fixture)
    pool_comparisons = []
    for zero_row, positive_row in zip(
        zero_retirement["ppe"], positive_retirement["ppe"]
    ):
        zero_pools = {pool["id"]: pool for pool in zero_row["pools"]}
        positive_pools = {pool["id"]: pool for pool in positive_row["pools"]}
        for pool_id in sorted(zero_pools):
            zero_pool = zero_pools[pool_id]
            positive_pool = positive_pools[pool_id]
            zero_active_gross = (
                zero_pool["closing_gross"]
                if zero_pool["closing_net"] > tolerance
                else 0.0
            )
            positive_active_gross = (
                positive_pool["closing_gross"]
                if positive_pool["closing_net"] > tolerance
                else 0.0
            )
            active_gross_residual = positive_active_gross - zero_active_gross
            cumulative_retirement_difference = (
                zero_pool["closing_gross"] - positive_pool["closing_gross"]
            )
            accumulated_change_residual = (
                positive_pool["closing_accumulated_depreciation"]
                - zero_pool["closing_accumulated_depreciation"]
            ) + cumulative_retirement_difference
            closing_net_residual = (
                positive_pool["closing_net"] - zero_pool["closing_net"]
            )
            depreciation_residual = (
                positive_pool["depreciation"] - zero_pool["depreciation"]
            )
            pool_comparisons.append(
                {
                    "year": zero_row["year"],
                    "pool": pool_id,
                    "zero_active_gross_depreciable_basis": zero_active_gross,
                    "positive_active_gross_depreciable_basis": positive_active_gross,
                    "active_gross_basis_residual": active_gross_residual,
                    "zero_closing_accumulated_depreciation": zero_pool[
                        "closing_accumulated_depreciation"
                    ],
                    "positive_closing_accumulated_depreciation": positive_pool[
                        "closing_accumulated_depreciation"
                    ],
                    "retirement_accumulated_depreciation": positive_pool[
                        "retirement_accumulated_depreciation"
                    ],
                    "accumulated_depreciation_change_residual": accumulated_change_residual,
                    "zero_closing_net_basis": zero_pool["closing_net"],
                    "positive_closing_net_basis": positive_pool["closing_net"],
                    "closing_net_basis_residual": closing_net_residual,
                    "depreciation_residual": depreciation_residual,
                    "matches_within_tolerance": max(
                        abs(active_gross_residual),
                        abs(accumulated_change_residual),
                        abs(closing_net_residual),
                        abs(depreciation_residual),
                    )
                    <= tolerance,
                }
            )
    economic_fields = {
        "ebit": ("income_statement", "ebit"),
        "tax": ("income_statement", "taxes"),
        "operating_cash_flow": ("cash_flow", "operating_cash_flow"),
        "net_change_cash": ("cash_flow", "net_change_cash"),
        "fcff": ("fcff", "fcff"),
    }
    economic_comparisons = {}
    for label, location in economic_fields.items():
        schedule_name, field = location
        zero_values = [row[field] for row in zero_retirement[schedule_name]]
        positive_values = [row[field] for row in positive_retirement[schedule_name]]
        residuals = [
            positive - zero for zero, positive in zip(zero_values, positive_values)
        ]
        economic_comparisons[label] = {
            "zero_disposal_values": zero_values,
            "positive_disposal_values": positive_values,
            "residuals": residuals,
            "matches_within_tolerance": all(
                abs(residual) <= tolerance for residual in residuals
            ),
        }
    retirement_matching = [
        row["retirement_gross_cost"] - row["retirement_accumulated_depreciation"]
        for row in positive_retirement["ppe"]
    ]
    disposal_probes = {
        "fixture": {
            "zero_disposal_rate": 0.0,
            "positive_disposal_rate": retirement_fixture["disposal_rate"],
        },
        "zero_retirement_gross_cost": [
            x["retirement_gross_cost"] for x in zero_retirement["ppe"]
        ],
        "positive_retirement_gross_cost": [
            x["retirement_gross_cost"] for x in positive_retirement["ppe"]
        ],
        "positive_retirement_accumulated_depreciation": [
            x["retirement_accumulated_depreciation"] for x in positive_retirement["ppe"]
        ],
        "retirement_matching_residuals": retirement_matching,
        "pool_level_basis_and_accumulated_depreciation_comparisons": pool_comparisons,
        "economic_invariance_comparisons": economic_comparisons,
    }
    disposal_ok = (
        all(x == 0.0 for x in disposal_probes["zero_retirement_gross_cost"])
        and any(
            x > tolerance for x in disposal_probes["positive_retirement_gross_cost"]
        )
        and all(abs(residual) <= tolerance for residual in retirement_matching)
        and all(item["matches_within_tolerance"] for item in pool_comparisons)
        and all(
            item["matches_within_tolerance"] for item in economic_comparisons.values()
        )
    )
    final_cap_fixture = balanced(
        {
            "opening_cash": 0.0,
            "opening_receivables": 0.0,
            "opening_inventory": 0.0,
            "opening_ppe": 0.0,
            "opening_payables": 0.0,
            "opening_other_liabilities": 0.0,
            "opening_term_debt": 0.0,
            "opening_revolver": 0.0,
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 0.0,
            "capex": [100.0, 0.0, 0.0, 0.0, 0.0],
            "new_capex_life": 1.0,
            "minimum_cash": 0.0,
            "mandatory_amortization": 0.0,
            "disposal_rate": 0.0,
        }
    )
    final_cap_schedule = schedule(final_cap_fixture)
    final_cap_entry = next(
        pool
        for pool in final_cap_schedule["ppe"][0]["pools"]
        if pool["id"] == "capex_1"
    )
    final_cap_exit = next(
        pool
        for pool in final_cap_schedule["ppe"][1]["pools"]
        if pool["id"] == "capex_1"
    )
    final_cap_evidence = {
        "entry_year_depreciation": final_cap_entry["depreciation"],
        "later_year_depreciation": final_cap_exit["depreciation"],
        "later_year_opening_net": final_cap_exit["opening_net"],
        "later_year_closing_net": final_cap_exit["closing_net"],
        "expected_entry_half_charge": 50.0,
        "expected_final_capped_charge": 50.0,
    }
    final_cap_ok = (
        abs(final_cap_entry["depreciation"] - 50.0) <= tolerance
        and abs(final_cap_exit["depreciation"] - 50.0) <= tolerance
        and abs(final_cap_exit["closing_net"]) <= tolerance
    )

    debt_residuals, interest_residuals, statement_residuals = [], [], []
    for i, row in enumerate(financing):
        debt_residuals.extend(
            [
                abs(
                    row["closing_term_debt"]
                    - row["opening_term_debt"]
                    + row["mandatory_amortization"]
                    + row["term_sweep"]
                ),
                abs(
                    row["closing_revolver"]
                    - row["opening_revolver"]
                    - row["revolver_draw"]
                    + row["revolver_sweep"]
                ),
            ]
        )
        interest_residuals.append(
            max(
                abs(
                    row["interest_expense"]
                    - inputs["debt_interest_rate"]
                    * (
                        row["opening_term_debt"]
                        + row["opening_revolver"]
                        + row["closing_term_debt"]
                        + row["closing_revolver"]
                    )
                    / 2
                ),
                abs(
                    row["interest_income"]
                    - inputs["cash_interest_rate"]
                    * (
                        max(row["opening_cash"] - inputs["minimum_cash"], 0.0)
                        + max(row["closing_cash"] - inputs["minimum_cash"], 0.0)
                    )
                    / 2
                ),
                row["convergence_residual"],
            )
        )
        independently_summed_assets = (
            bs[i]["cash"] + bs[i]["receivables"] + bs[i]["inventory"] + bs[i]["net_ppe"]
        )
        independently_summed_claims = (
            bs[i]["payables"]
            + bs[i]["other_current_liabilities"]
            + bs[i]["term_debt"]
            + bs[i]["revolver"]
            + bs[i]["equity"]
        )
        independently_reconstructed_operating = (
            cf[i]["net_income"]
            + cf[i]["depreciation"]
            + cf[i]["recurring_working_capital"]
            + cf[i]["normalization_working_capital"]
        )
        independently_reconstructed_investing = -cf[i]["capex"]
        independently_reconstructed_financing = (
            cf[i]["mandatory_amortization"]
            + cf[i]["revolver_draw"]
            + cf[i]["revolver_sweep"]
            + cf[i]["term_sweep"]
        )
        independently_reconstructed_change = (
            independently_reconstructed_operating
            + independently_reconstructed_investing
            + independently_reconstructed_financing
        )
        statement_residuals.append(
            max(
                abs(independently_summed_assets - independently_summed_claims),
                abs(
                    cf[i]["operating_cash_flow"] - independently_reconstructed_operating
                ),
                abs(
                    cf[i]["investing_cash_flow"] - independently_reconstructed_investing
                ),
                abs(
                    cf[i]["financing_cash_flow"] - independently_reconstructed_financing
                ),
                abs(
                    cf[i]["beginning_cash"]
                    + independently_reconstructed_change
                    - cf[i]["ending_cash"]
                ),
                abs(
                    retained[i]["closing_equity"]
                    - retained[i]["opening_equity"]
                    - income[i]["net_income"]
                ),
            )
        )
    exact_fixture = balanced(
        {
            "opening_cash": 1000.0,
            "opening_receivables": 0.0,
            "opening_inventory": 0.0,
            "opening_ppe": 0.0,
            "opening_payables": 0.0,
            "opening_other_liabilities": 0.0,
            "opening_term_debt": 0.0,
            "opening_revolver": 0.0,
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 0.0,
            "capex": 0.0,
            "minimum_cash": 1000.0,
            "mandatory_amortization": 0.0,
            "cash_sweep_pct": 1.0,
            "debt_interest_rate": 0.0,
            "cash_interest_rate": 0.0,
        }
    )
    draw_fixture = balanced(
        {
            "opening_cash": 0.0,
            "opening_receivables": 0.0,
            "opening_inventory": 0.0,
            "opening_ppe": 0.0,
            "opening_payables": 0.0,
            "opening_other_liabilities": 0.0,
            "opening_term_debt": 0.0,
            "opening_revolver": 0.0,
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 100.0,
            "capex": 0.0,
            "minimum_cash": 1000.0,
            "mandatory_amortization": 0.0,
            "cash_sweep_pct": 1.0,
            "debt_interest_rate": 0.0,
        }
    )
    revolver_first_fixture = balanced(
        {
            "opening_cash": 2000000.0,
            "opening_revolver": 1000000.0,
            "opening_term_debt": 1000000.0,
            "mandatory_amortization": 0.0,
            "cash_sweep_pct": 1.0,
        }
    )
    exact_financing, draw_financing, rev_first_financing = (
        schedule(exact_fixture)["financing"][0],
        schedule(draw_fixture)["financing"][0],
        schedule(revolver_first_fixture)["financing"][0],
    )
    term_only_fixture = balanced(
        {
            "opening_cash": 2000000.0,
            "opening_revolver": 0.0,
            "opening_term_debt": 1000000.0,
            "mandatory_amortization": 0.0,
            "cash_sweep_pct": 1.0,
        }
    )
    term_only = schedule(term_only_fixture)["financing"][0]
    branch_evidence = {
        "no_draw_exact_boundary": exact_financing,
        "draw": draw_financing,
        "revolver_first": rev_first_financing,
        "term_only": term_only,
    }
    branch_ok = (
        exact_financing["revolver_draw"] <= tolerance
        and exact_financing["term_sweep"] <= tolerance
        and draw_financing["revolver_draw"] > tolerance
        and rev_first_financing["revolver_sweep"] > tolerance
        and abs(
            rev_first_financing["revolver_sweep"]
            - min(
                rev_first_financing["sweep_capacity"],
                rev_first_financing["opening_revolver"],
            )
        )
        <= tolerance
        and term_only["revolver_sweep"] <= tolerance
        and term_only["term_sweep"] > tolerance
    )

    fcff_residuals = []
    for i, row in enumerate(data["fcff"]):
        expected = (
            ops[i]["ebit"]
            - max(ops[i]["ebit"], 0.0) * inputs["tax_rate"]
            + ppe[i]["depreciation"]
            - ppe[i]["capex"]
            + wc[i]["recurring_cash_flow"]
            + wc[i]["normalization_cash_flow"]
        )
        fcff_residuals.append(abs(row["fcff"] - expected))
    expected_terminal = ops[-1]["ebitda"] * inputs["exit_multiple"]
    terminal_pv = expected_terminal / (1 + inputs["wacc"]) ** 5
    expected_ev = (
        sum(
            row["fcff"] / (1 + inputs["wacc"]) ** (i + 1)
            for i, row in enumerate(data["fcff"])
        )
        + terminal_pv
    )
    bridge = (
        valuation["equity_value"]
        - valuation["enterprise_value"]
        - inputs["opening_cash"]
        + inputs["opening_term_debt"]
        + inputs["opening_revolver"]
    )
    opening_cash_probe = schedule(
        balanced({"opening_cash": inputs["opening_cash"] + 100000.0})
    )
    opening_debt_probe = schedule(
        balanced({"opening_term_debt": inputs["opening_term_debt"] + 100000.0})
    )
    amortization_probe = schedule(clone(inputs, {"mandatory_amortization": 0.0}))
    sweep_probe = schedule(
        clone(
            inputs, {"cash_sweep_pct": 1.0 if inputs["cash_sweep_pct"] < 1.0 else 0.0}
        )
    )
    opening_bridge_evidence = {
        "submitted_raw_opening_bridge": {
            "enterprise_value": valuation["enterprise_value"],
            "opening_cash": inputs["opening_cash"],
            "opening_term_debt": inputs["opening_term_debt"],
            "opening_revolver": inputs["opening_revolver"],
            "reconstructed_equity_value": valuation["enterprise_value"]
            + inputs["opening_cash"]
            - inputs["opening_term_debt"]
            - inputs["opening_revolver"],
            "reported_equity_value": valuation["equity_value"],
            "residual": bridge,
        },
        "opening_cash_change": {
            "enterprise_value_change": opening_cash_probe["valuation"][
                "enterprise_value"
            ]
            - valuation["enterprise_value"],
            "equity_value_change": opening_cash_probe["valuation"]["equity_value"]
            - valuation["equity_value"],
        },
        "opening_debt_change": {
            "enterprise_value_change": opening_debt_probe["valuation"][
                "enterprise_value"
            ]
            - valuation["enterprise_value"],
            "equity_value_change": opening_debt_probe["valuation"]["equity_value"]
            - valuation["equity_value"],
        },
        "terminal_financing_changes": {
            "amortization": {
                "terminal_net_debt_change": amortization_probe["valuation"]["net_debt"]
                - valuation["net_debt"],
                "enterprise_value_change": amortization_probe["valuation"][
                    "enterprise_value"
                ]
                - valuation["enterprise_value"],
                "opening_bridge_change": amortization_probe["valuation"][
                    "opening_net_debt"
                ]
                - valuation["opening_net_debt"],
            },
            "sweep": {
                "terminal_net_debt_change": sweep_probe["valuation"]["net_debt"]
                - valuation["net_debt"],
                "enterprise_value_change": sweep_probe["valuation"]["enterprise_value"]
                - valuation["enterprise_value"],
                "opening_bridge_change": sweep_probe["valuation"]["opening_net_debt"]
                - valuation["opening_net_debt"],
            },
        },
    }
    opening_bridge_probe_ok = (
        abs(
            opening_cash_probe["valuation"]["enterprise_value"]
            - valuation["enterprise_value"]
        )
        <= tolerance
        and abs(
            opening_debt_probe["valuation"]["enterprise_value"]
            - valuation["enterprise_value"]
        )
        <= tolerance
        and abs(
            opening_cash_probe["valuation"]["equity_value"]
            - valuation["equity_value"]
            - 100000.0
        )
        <= tolerance
        and abs(
            opening_debt_probe["valuation"]["equity_value"]
            - valuation["equity_value"]
            + 100000.0
        )
        <= tolerance
    )
    terminal_financing_probe_ok = all(
        abs(probe["enterprise_value_change"]) <= tolerance
        and abs(probe["opening_bridge_change"]) <= tolerance
        for probe in opening_bridge_evidence["terminal_financing_changes"].values()
    )
    sensitivity_residuals, sensitivity_coordinates = [], []
    for matrix_row in valuation["sensitivity"]:
        multiple = matrix_row["exit_multiple"]
        for column, rate in enumerate([0.07, 0.08, 0.09, 0.10, 0.11]):
            reconstructed = (
                sum(
                    row["fcff"] / (1 + rate) ** (i + 1)
                    for i, row in enumerate(data["fcff"])
                )
                + ops[-1]["ebitda"] * multiple / (1 + rate) ** 5
                + inputs["opening_cash"]
                - inputs["opening_term_debt"]
                - inputs["opening_revolver"]
            )
            residual = matrix_row["values"][column] - reconstructed
            sensitivity_residuals.append(abs(residual))
            sensitivity_coordinates.append(
                {"multiple": multiple, "wacc": rate, "residual": residual}
            )
    multiple_changes = [
        valuation["sensitivity"][r + 1]["values"][c]
        - valuation["sensitivity"][r]["values"][c]
        for r in range(4)
        for c in range(5)
    ]
    multiple_ok = (
        all(x >= -tolerance for x in multiple_changes)
        if ops[-1]["ebitda"] >= 0
        else all(x <= tolerance for x in multiple_changes)
    )
    nonflat = (
        any(abs(x) > tolerance for x in multiple_changes)
        if abs(ops[-1]["ebitda"]) > tolerance
        else True
    )
    wacc_observed = [
        [
            valuation["sensitivity"][r]["values"][c + 1]
            - valuation["sensitivity"][r]["values"][c]
            for c in range(4)
        ]
        for r in range(5)
    ]
    wacc_direction_rounding_tolerance = 0.000001
    conventional_wacc_direction_supported = (
        all(row["fcff"] >= -wacc_direction_rounding_tolerance for row in data["fcff"])
        and ops[-1]["ebitda"] >= -wacc_direction_rounding_tolerance
    )
    wacc_non_increasing = all(
        change <= wacc_direction_rounding_tolerance
        for row in wacc_observed
        for change in row
    )
    observed_warning = any(
        change > wacc_direction_rounding_tolerance
        for row in wacc_observed
        for change in row
    )
    rounding_fixtures = [
        {
            "name": "below_tolerance",
            "adjacent_change": 0.000000999999,
            "non_increasing": 0.000000999999 <= wacc_direction_rounding_tolerance,
        },
        {
            "name": "at_tolerance",
            "adjacent_change": 0.000001,
            "non_increasing": 0.000001 <= wacc_direction_rounding_tolerance,
        },
        {
            "name": "above_tolerance",
            "adjacent_change": 0.000001000001,
            "non_increasing": 0.000001000001 <= wacc_direction_rounding_tolerance,
        },
    ]
    rounding_fixture_ok = (
        rounding_fixtures[0]["non_increasing"]
        and rounding_fixtures[1]["non_increasing"]
        and not rounding_fixtures[2]["non_increasing"]
    )
    expected_wacc_status = (
        "conventional_non_increasing_verified"
        if conventional_wacc_direction_supported and wacc_non_increasing
        else (
            "conventional_non_increasing_failed"
            if conventional_wacc_direction_supported
            else (
                "non_monotonic_signed_fcff_warning"
                if observed_warning
                else "signed_fcff_nonconventional_non_increasing"
            )
        )
    )
    direction_status_ok = (
        valuation.get("wacc_direction_rounding_tolerance")
        == wacc_direction_rounding_tolerance
        and valuation["conventional_wacc_direction_supported"]
        == conventional_wacc_direction_supported
        and valuation["wacc_direction_status"] == expected_wacc_status
        and (not conventional_wacc_direction_supported or wacc_non_increasing)
        and (
            valuation["wacc_direction_warning"] is not None
            if observed_warning
            else True
        )
        and rounding_fixture_ok
    )
    grid_rates = [0.07, 0.08, 0.09, 0.10, 0.11]
    selected_column = next(
        (
            i
            for i, rate in enumerate(grid_rates)
            if abs(rate - inputs["wacc"]) <= 0.0000001
        ),
        None,
    )
    selected_tie = (
        next(
            row["values"][selected_column]
            for row in valuation["sensitivity"]
            if abs(row["exit_multiple"] - inputs["exit_multiple"]) <= 0.0000001
        )
        if selected_column is not None
        and inputs["exit_multiple"] in [5.0, 5.5, 6.0, 6.5, 7.0]
        else None
    )
    sensitivity_ok = (
        valuation.get("sensitivity_value_type") == "equity_value"
        and max(sensitivity_residuals) <= tolerance
        and multiple_ok
        and nonflat
        and direction_status_ok
        and (
            selected_tie is None
            or abs(selected_tie - valuation["equity_value"]) <= tolerance
        )
    )

    required_keys = [
        "periods",
        "paint",
        "tools",
        "operations",
        "working_capital",
        "opening_working_capital",
        "ppe",
        "financing",
        "income_statement",
        "cash_flow",
        "balance_sheet",
        "retained_earnings",
        "fcff",
        "valuation",
        "integrity_status",
    ]
    debt_fields = [
        "term_rollforward_residuals",
        "revolver_rollforward_residuals",
        "mandatory_amortization_cap_statuses",
        "repayment_availability_statuses",
        "revolver_first_allocation_statuses",
        "draw_sweep_exclusivity_residuals",
        "debt_nonnegative_statuses",
    ]
    operating_metric_fields = {
        "paint": [
            "revenue_per_unit",
            "variable_cost_per_unit",
            "gross_profit_per_unit",
        ],
        "tools": [
            "revenue_per_unit",
            "purchase_cost_per_unit",
            "gross_profit_per_unit",
        ],
        "operations": ["gross_margin"],
    }
    operating_metrics_present = (
        all(
            all(field in row for field in operating_metric_fields["paint"])
            for row in data["paint"]
        )
        and all(
            all(field in row for field in operating_metric_fields["tools"])
            for row in data["tools"]
        )
        and all("gross_margin" in row for row in data["operations"])
    )
    integrity_keys = [
        "balance_sheet",
        "cash_flow",
        "debt_sweep",
        "ppe",
        "retained_earnings",
        "minimum_cash",
        "interest_convergence",
        "enterprise_to_equity_bridge",
    ]
    summary_blocks = [
        block
        for block in outputs["output_blocks"]
        if block.get("id") == "executive_summary"
    ]
    summary = summary_blocks[0].get("data", {}) if len(summary_blocks) == 1 else {}
    summary_sources = {
        "year_5_revenue": data["operations"][-1]["revenue"],
        "year_5_ebitda": data["operations"][-1]["ebitda"],
        "year_5_ebitda_margin": data["operations"][-1]["ebitda_margin"],
        "year_5_ebit": data["income_statement"][-1]["ebit"],
        "year_5_net_income": data["income_statement"][-1]["net_income"],
        "ending_cash": data["balance_sheet"][-1]["cash"],
        "ending_term_debt": data["valuation"]["terminal_term_debt"],
        "ending_revolver": data["valuation"]["terminal_revolver"],
        "ending_total_debt": data["valuation"]["terminal_total_debt"],
        "net_debt": data["valuation"]["net_debt"],
        "enterprise_value": data["valuation"]["enterprise_value"],
        "opening_date_equity_value": data["valuation"]["equity_value"],
        "terminal_present_value_contribution": data["valuation"][
            "terminal_present_value"
        ],
        "maximum_interest_convergence_residual": data["integrity_status"][
            "interest_convergence"
        ]["maximum_convergence_residual"],
    }
    summary_paths = {
        "year_5_revenue": "output_blocks.0.data.year_5_revenue",
        "year_5_ebitda": "output_blocks.0.data.year_5_ebitda",
        "year_5_ebitda_margin": "output_blocks.0.data.year_5_ebitda_margin",
        "year_5_ebit": "output_blocks.0.data.year_5_ebit",
        "year_5_net_income": "output_blocks.0.data.year_5_net_income",
        "ending_cash": "output_blocks.0.data.ending_cash",
        "ending_term_debt": "output_blocks.0.data.ending_term_debt",
        "ending_revolver": "output_blocks.0.data.ending_revolver",
        "ending_total_debt": "output_blocks.0.data.ending_total_debt",
        "net_debt": "output_blocks.0.data.net_debt",
        "enterprise_value": "output_blocks.0.data.enterprise_value",
        "opening_date_equity_value": "output_blocks.0.data.opening_date_equity_value",
        "terminal_present_value_contribution": "output_blocks.0.data.terminal_present_value_contribution",
        "maximum_interest_convergence_residual": "output_blocks.0.data.maximum_interest_convergence_residual",
    }
    missing_summary_fields = [
        key
        for key in list(summary_sources)
        + ["current_case_only", "period", "valuation_date", "integrity_pass_statuses"]
        if key not in summary
    ]
    summary_value_residuals = {
        key: (
            None
            if summary.get(key) is None or expected is None
            else summary[key] - expected
        )
        for key, expected in summary_sources.items()
    }
    summary_values_tied = not missing_summary_fields and all(
        residual is None or abs(residual) <= tolerance
        for residual in summary_value_residuals.values()
    )
    summary_metadata_tied = (
        summary.get("current_case_only") is True
        and summary.get("period") == data["periods"][-1]
        and summary.get("valuation_date") == "opening_date"
    )
    summary_integrity_tied = (
        isinstance(summary.get("integrity_pass_statuses"), dict)
        and set(summary.get("integrity_pass_statuses", {})) == set(integrity_keys)
        and all(
            summary["integrity_pass_statuses"].get(key)
            == data["integrity_status"][key]["passed"]
            for key in integrity_keys
        )
    )
    minimum_cash_fields_present = (
        "headroom" in data["integrity_status"]["minimum_cash"]
        and "compliance_statuses" in data["integrity_status"]["minimum_cash"]
        and "residuals" not in data["integrity_status"]["minimum_cash"]
        and len(data["integrity_status"]["minimum_cash"].get("headroom", [])) == 5
        and len(data["integrity_status"]["minimum_cash"].get("compliance_statuses", []))
        == 5
    )
    required = (
        all(key in data for key in required_keys)
        and len(data["periods"]) == 5
        and all(
            len(data[key]) == 5
            for key in [
                "paint",
                "tools",
                "operations",
                "working_capital",
                "ppe",
                "financing",
                "income_statement",
                "cash_flow",
                "balance_sheet",
                "retained_earnings",
                "fcff",
            ]
        )
        and operating_metrics_present
        and all(key in data["integrity_status"] for key in integrity_keys)
        and all(key in data["integrity_status"]["debt_sweep"] for key in debt_fields)
        and "active_basis_rollforward_residuals" in data["integrity_status"]["ppe"]
        and minimum_cash_fields_present
        and len(summary_blocks) == 1
        and summary_values_tied
        and summary_metadata_tied
        and summary_integrity_tied
    )

    base_calibration = {
        "opening_cash": 1500000,
        "opening_receivables": 2200000,
        "opening_inventory": 3500000,
        "opening_ppe": 12800000,
        "opening_payables": 2000000,
        "opening_other_liabilities": 500000,
        "opening_term_debt": 10000000,
        "opening_revolver": 0,
        "opening_equity": 7500000,
        "paint_units": 400000,
        "paint_price": 32,
        "paint_unit_cost": 14,
        "paint_overhead": 1500000,
        "tools_units": 300000,
        "tools_price": 18,
        "tools_unit_cost": 10,
        "tools_storage": 600000,
        "corporate_opex": 3000000,
        "paint_unit_growth": 0.03,
        "paint_price_inflation": 0.02,
        "paint_cost_inflation": 0.02,
        "paint_overhead_inflation": 0.02,
        "tools_unit_growth": 0.02,
        "tools_price_inflation": 0.02,
        "tools_cost_inflation": 0.02,
        "tools_storage_inflation": 0.02,
        "corporate_opex_inflation": 0.02,
        "receivable_days": 55,
        "inventory_days": 75,
        "payable_days": 50,
        "capex": 1500000,
        "opening_ppe_life": 10,
        "new_capex_life": 10,
        "disposal_rate": 0.01,
        "minimum_cash": 1000000,
        "mandatory_amortization": 800000,
        "debt_interest_rate": 0.06,
        "cash_interest_rate": 0.02,
        "cash_sweep_pct": 0.5,
        "tax_rate": 0.25,
        "wacc": 0.09,
        "exit_multiple": 6,
    }
    calibration_comparisons = {
        name: {
            "expected": expected,
            "actual": inputs.get(name),
            "matches": inputs.get(name) == expected,
        }
        for name, expected in base_calibration.items()
    }
    missing_raw_keys = sorted(set(base_calibration) - set(inputs))
    unexpected_raw_keys = sorted(set(inputs) - set(base_calibration))
    raw_key_match = not missing_raw_keys and not unexpected_raw_keys
    raw_value_match = all(item["matches"] for item in calibration_comparisons.values())
    is_base_fixture = raw_key_match and raw_value_match
    differing_input_names = [
        name
        for name, comparison in calibration_comparisons.items()
        if not comparison["matches"]
    ]
    observed_case_distinction = (
        "unmodified_saved_base_fixture" if is_base_fixture else "changed_input_case"
    )
    case_reason = "Base-only opening-balance-sheet calibration does not apply because the submitted raw inputs differ from the saved Base fixture"
    if missing_raw_keys or unexpected_raw_keys:
        case_reason = "Base-only opening-balance-sheet calibration does not apply because the submitted raw input keys do not exactly match the saved Base fixture"
    calibration_evidence = {
        "not_applicable": not is_base_fixture,
        "observed_case_distinction": observed_case_distinction,
        "raw_key_match": raw_key_match,
        "raw_value_match": raw_value_match,
        "calibration_assertion_passed": True if is_base_fixture else None,
        "comparisons": calibration_comparisons,
        "differing_input_names": differing_input_names,
        "missing_raw_keys": missing_raw_keys,
        "unexpected_raw_keys": unexpected_raw_keys,
        "skip_reason": None if is_base_fixture else case_reason,
    }
    zero_revenue_fixture = balanced(
        {
            "paint_units": 0.0,
            "paint_price": 0.0,
            "paint_unit_cost": 0.0,
            "paint_overhead": 0.0,
            "tools_units": 0.0,
            "tools_price": 0.0,
            "tools_unit_cost": 0.0,
            "tools_storage": 0.0,
            "corporate_opex": 0.0,
            "capex": 0.0,
            "mandatory_amortization": 0.0,
            "debt_interest_rate": 0.0,
            "cash_interest_rate": 0.0,
            "cash_sweep_pct": 0.0,
            "disposal_rate": 0.0,
            "receivable_days": 0.0,
            "inventory_days": 0.0,
            "payable_days": 0.0,
            "exit_multiple": 0.0,
        }
    )
    zero_controls_fixture = clone(
        inputs,
        {
            "capex": 0.0,
            "mandatory_amortization": 0.0,
            "debt_interest_rate": 0.0,
            "cash_interest_rate": 0.0,
            "cash_sweep_pct": 0.0,
            "disposal_rate": 0.0,
            "receivable_days": 0.0,
            "inventory_days": 0.0,
            "payable_days": 0.0,
            "exit_multiple": 0.0,
        },
    )
    zero_revenue_schedule = schedule(zero_revenue_fixture)
    zero_controls_schedule = schedule(zero_controls_fixture)
    zero_safe_evidence = {
        "zero_revenue_fixture": {
            "finite": finite(zero_revenue_schedule),
            "paint_margin": zero_revenue_schedule["paint"][0]["gross_margin"],
            "tools_margin": zero_revenue_schedule["tools"][0]["gross_margin"],
            "ebitda_margin": zero_revenue_schedule["operations"][0]["ebitda_margin"],
            "terminal_value": zero_revenue_schedule["valuation"]["terminal_value"],
            "capex": zero_revenue_schedule["ppe"][0]["capex"],
            "receivables": zero_revenue_schedule["working_capital"][0]["receivables"],
            "inventory": zero_revenue_schedule["working_capital"][0]["inventory"],
            "payables": zero_revenue_schedule["working_capital"][0]["payables"],
        },
        "zero_controls_fixture": {
            "finite": finite(zero_controls_schedule),
            "capex": zero_controls_schedule["ppe"][0]["capex"],
            "mandatory_amortization": zero_controls_schedule["financing"][0][
                "mandatory_amortization"
            ],
            "interest_expense": zero_controls_schedule["financing"][0][
                "interest_expense"
            ],
            "interest_income": zero_controls_schedule["financing"][0][
                "interest_income"
            ],
            "sweep_capacity": zero_controls_schedule["financing"][0]["sweep_capacity"],
            "retirement_gross_cost": zero_controls_schedule["ppe"][0][
                "retirement_gross_cost"
            ],
            "receivables": zero_controls_schedule["working_capital"][0]["receivables"],
            "inventory": zero_controls_schedule["working_capital"][0]["inventory"],
            "payables": zero_controls_schedule["working_capital"][0]["payables"],
            "terminal_value": zero_controls_schedule["valuation"]["terminal_value"],
        },
    }
    zero_safe_ok = (
        finite(data)
        and all(item["finite"] for item in zero_safe_evidence.values())
        and zero_safe_evidence["zero_revenue_fixture"]["paint_margin"] is None
        and zero_safe_evidence["zero_revenue_fixture"]["tools_margin"] is None
        and zero_safe_evidence["zero_revenue_fixture"]["ebitda_margin"] is None
        and zero_safe_evidence["zero_revenue_fixture"]["terminal_value"] == 0.0
        and zero_safe_evidence["zero_controls_fixture"]["terminal_value"] == 0.0
    )

    reported_convergence_tolerances = [
        row["convergence_tolerance"] for row in financing
    ]

    production_tolerance = reported_convergence_tolerances[0]
    convergence_boundary_fixtures = []
    for name, residual in [
        ("below_tolerance", production_tolerance - 0.000000001),
        ("at_tolerance", production_tolerance),
        ("above_tolerance", production_tolerance + 0.000000001),
    ]:
        implemented = convergence_status(residual, production_tolerance)
        convergence_boundary_fixtures.append(
            {
                "name": name,
                "fixture_residual": residual,
                "configured_tolerance": production_tolerance,
                "implemented_status": implemented["status"],
                "implemented_converged": implemented["converged"],
                "passed": implemented["passed"],
            }
        )
    convergence_boundary_ok = (
        convergence_boundary_fixtures[0]["implemented_converged"]
        and convergence_boundary_fixtures[1]["implemented_converged"]
        and not convergence_boundary_fixtures[2]["implemented_converged"]
    )

    checks = [
        result(
            "input_bounds_and_finiteness",
            finite(data) and validation_passed,
            "Every scalar domain and five-period flexible-control validation branch is exercised against raw fixtures.",
            {
                "scalar_validation": validation_evidence,
                "flexible_controls": flexible_evidence,
            },
        ),
        result(
            "opening_balance_sheet_identity",
            abs(opening_assets - opening_claims) <= tolerance
            and alternative_ok
            and unbalanced_rejected,
            "Opening identity is independently summed from submitted inputs and tested on balanced and unbalanced alternatives.",
            {
                "submitted_residual": opening_assets - opening_claims,
                "alternative_fixture": alternative,
                "alternative_passed": alternative_ok,
                "unbalanced_rejected": unbalanced_rejected,
            },
        ),
        result(
            "base_fixture_default_calibration",
            is_base_fixture,
            (
                "Saved Base calibration passed for the exact saved raw Base fixture."
                if is_base_fixture
                else "Skipped: Base-only opening-balance-sheet calibration is not applicable to this changed-input raw case."
            ),
            calibration_evidence,
            "passed" if is_base_fixture else "skipped",
        ),
        result(
            "segment_operations_and_consolidation",
            max(segment_residuals) <= tolerance and zero_segment_ok,
            "Segment revenue, direct costs, fixed direct expenses, gross profit, margins, and consolidated results are independently reconstructed with executed zero cases.",
            {"by_year": segment_evidence, "zero_execution": zero_segment_evidence},
        ),
        result(
            "working_capital_normalization_and_recurring_movement",
            max(wc_residuals) <= tolerance
            and zero_days_ok
            and full_days_ok
            and finite(zero_days_schedule)
            and finite(full_days_schedule),
            "Reported and normalized opening working capital plus recurring movements and executed 0-day/365-day boundaries are independently reconstructed.",
            {
                "reported_opening_nwc": inputs["opening_receivables"]
                + inputs["opening_inventory"]
                - inputs["opening_payables"],
                "normalized_opening_nwc": normalized,
                "residuals": wc_residuals,
                "boundary_executions": wc_boundary_evidence,
            },
        ),
        result(
            "ppe_pool_roll_forward_and_disposal_behavior",
            max(ppe_residuals + depreciation_residuals + retirement_residuals)
            <= tolerance
            and all(retirement_eligibility)
            and disposal_ok
            and final_cap_ok,
            "PP&E active basis, independently calculated straight-line half-year/full-year depreciation, final caps, and zero-NBV retirement availability are verified.",
            {
                "rollforward_residuals": ppe_residuals,
                "depreciation_residuals": depreciation_residuals,
                "depreciation_by_pool": depreciation_evidence,
                "final_cap_fixture": final_cap_evidence,
                "retirement_matching_residuals": retirement_residuals,
                "retirement_eligibility_statuses": retirement_eligibility,
                "disposal_fixture": disposal_probes,
            },
        ),
        result(
            "cash_debt_roll_forward_and_minimum_cash",
            max(debt_residuals) <= tolerance
            and all(
                row["closing_cash"] >= inputs["minimum_cash"] - tolerance
                for row in financing
            )
            and branch_ok,
            "Debt, cash, minimum-cash and all required financing branch fixtures are independently reconciled.",
            {"debt_residuals": debt_residuals, "branch_fixtures": branch_evidence},
        ),
        result(
            "sweep_priority_and_draw_sweep_exclusivity",
            all(
                row["revolver_draw"] * (row["revolver_sweep"] + row["term_sweep"])
                <= tolerance
                and row["revolver_sweep"]
                <= min(row["sweep_capacity"], row["opening_revolver"]) + tolerance
                and row["term_sweep"]
                <= max(row["sweep_capacity"] - row["revolver_sweep"], 0.0) + tolerance
                for row in financing
            )
            and branch_ok,
            "Current rows and binding no-draw, draw, revolver-first, and term-only fixtures prove sweep priority and exclusivity.",
            {"branch_fixtures": branch_evidence},
        ),
        result(
            "interest_circularity_convergence",
            all(
                residual <= row["convergence_tolerance"]
                for residual, row in zip(interest_residuals, financing)
            )
            and all(row["converged"] and row["iterations"] <= 100 for row in financing)
            and convergence_boundary_ok,
            "Average debt and qualifying cash interest are independently reconstructed against each reported production convergence tolerance, including below/at/above boundary fixtures.",
            {
                "residuals": interest_residuals,
                "reported_convergence_tolerances": reported_convergence_tolerances,
                "iterations": [row["iterations"] for row in financing],
                "boundary_fixtures": convergence_boundary_fixtures,
                "boundary_fixtures_passed": convergence_boundary_ok,
            },
        ),
        result(
            "three_statement_and_retained_earnings_tie_out",
            max(statement_residuals) <= tolerance,
            "Balance sheet, cash-flow, and retained-earnings links are independently reconstructed.",
            {"residuals": statement_residuals},
        ),
        result(
            "fcff_dcf_and_equity_bridge_tie_out",
            max(fcff_residuals) <= tolerance
            and abs(valuation["terminal_value"] - expected_terminal) <= tolerance
            and abs(valuation["terminal_present_value"] - terminal_pv) <= tolerance
            and abs(valuation["enterprise_value"] - expected_ev) <= tolerance
            and abs(bridge) <= tolerance
            and opening_bridge_probe_ok
            and terminal_financing_probe_ok,
            "Signed terminal value and opening-date enterprise value are independently reconstructed; equity value uses only submitted opening cash, term debt, and revolver.",
            {
                "fcff_residuals": fcff_residuals,
                "year5_ebitda": ops[-1]["ebitda"],
                "exit_multiple": inputs["exit_multiple"],
                "signed_terminal_value": expected_terminal,
                "terminal_pv": terminal_pv,
                "enterprise_value_residual": valuation["enterprise_value"]
                - expected_ev,
                "opening_date_bridge_evidence": opening_bridge_evidence,
                "opening_cash_and_debt_probe_passed": opening_bridge_probe_ok,
                "terminal_financing_independence_passed": terminal_financing_probe_ok,
            },
        ),
        result(
            "valuation_sensitivity_monotonicity",
            sensitivity_ok,
            "Every sensitivity coordinate is reconstructed; WACC direction is enforced for an all-non-negative cash-flow profile and otherwise explicitly assessed and disclosed from signed FCFF.",
            {
                "sensitivity_value_type": valuation.get("sensitivity_value_type"),
                "coordinates": sensitivity_coordinates,
                "max_reconstruction_residual": max(sensitivity_residuals),
                "terminal_ebitda": ops[-1]["ebitda"],
                "signed_fcff_profile": valuation["signed_fcff_profile"],
                "multiple_direction_passed": multiple_ok,
                "nonflat_multiple_impact": nonflat,
                "wacc_adjacent_changes": wacc_observed,
                "wacc_direction_rounding_tolerance_eur": wacc_direction_rounding_tolerance,
                "rounding_boundary_fixtures": rounding_fixtures,
                "rounding_boundary_fixtures_passed": rounding_fixture_ok,
                "conventional_wacc_direction_supported": conventional_wacc_direction_supported,
                "wacc_non_increasing": wacc_non_increasing,
                "wacc_direction_status": valuation["wacc_direction_status"],
                "wacc_direction_warning": valuation["wacc_direction_warning"],
                "direction_status_passed": direction_status_ok,
                "selected_point_residual": (
                    None
                    if selected_tie is None
                    else selected_tie - valuation["equity_value"]
                ),
                "selected_point_primary_equity_value": valuation["equity_value"],
                "selected_point_enterprise_value": valuation["enterprise_value"],
                "selected_point_opening_net_debt_bridge": valuation["opening_net_debt"],
                "selected_point_equity_to_enterprise_difference_residual": (
                    None
                    if selected_tie is None
                    else (
                        valuation["enterprise_value"]
                        - selected_tie
                        - valuation["opening_net_debt"]
                    )
                ),
            },
        ),
        result(
            "zero_safe_output_behavior",
            zero_safe_ok,
            "Balanced zero-revenue and zero-control fixtures are executed and recursively scanned for finite values and null zero-revenue margins.",
            {"current_finite": finite(data), "fixture_executions": zero_safe_evidence},
        ),
        result(
            "required_output_presence",
            required,
            "All requested five-period schedules, explicit minimum-cash compliance fields, and independently tied current-case executive-summary fields are exposed.",
            {
                "period_count": len(data["periods"]),
                "debt_sweep_fields": debt_fields,
                "ppe_active_basis_field_present": "active_basis_rollforward_residuals"
                in data["integrity_status"]["ppe"],
                "operating_metric_fields": operating_metric_fields,
                "operating_metrics_present": operating_metrics_present,
                "minimum_cash_fields_present": minimum_cash_fields_present,
                "executive_summary_block_count": len(summary_blocks),
                "executive_summary_missing_fields": missing_summary_fields,
                "executive_summary_metadata_tied": summary_metadata_tied,
                "executive_summary_integrity_statuses_tied": summary_integrity_tied,
                "executive_summary_value_residuals": summary_value_residuals,
                "resolved_summary_paths": summary_paths,
            },
        ),
    ]
    return {"checks": checks}


def run_suite_checks(cases):
    required = {"base", "downside", "upside"}

    def finite(value):
        if isinstance(value, dict):
            return all(finite(item) for item in value.values())
        if isinstance(value, list):
            return all(finite(item) for item in value)
        return not isinstance(value, float) or math.isfinite(value)

    def fingerprint(value):
        text = repr(value)
        accumulator = 2166136261
        for character in text:
            accumulator = (accumulator ^ ord(character)) * 16777619 % 4294967296
        return format(accumulator, "08x")

    def raw_member(case):
        raw_keys = [key for key in ["raw_inputs", "inputs", "input"] if key in case]
        if len(raw_keys) != 1 or not isinstance(case[raw_keys[0]], dict):
            raise KeyError("exactly one platform raw-input member is required")
        return raw_keys[0], case[raw_keys[0]]

    def unpack(case):
        raw_key, raw = raw_member(case)
        output = case["output"]
        data = next(
            block["data"]
            for block in output["output_blocks"]
            if block["id"] == "financial_model"
        )
        executed_data = run_all(load_inputs(raw))
        pair_matches = executed_data == data
        financing = data["financing"]
        return {
            "revenue": data["operations"][-1]["revenue"],
            "ebitda": data["operations"][-1]["ebitda"],
            "fcff": data["fcff"][-1]["fcff"],
            "cash": data["balance_sheet"][-1]["cash"],
            "debt": data["valuation"]["terminal_term_debt"]
            + data["valuation"]["terminal_revolver"],
            "equity_value": data["valuation"]["equity_value"],
            "integrity": data["integrity_status"],
            "finite": finite(data),
            "draw_activated": any(row["revolver_draw"] > 0.000001 for row in financing),
            "sweep_activated": any(
                row["revolver_sweep"] + row["term_sweep"] > 0.000001
                for row in financing
            ),
            "pair_evidence": {
                "raw_input_member": raw_key,
                "raw_input_fingerprint": fingerprint(raw),
                "raw_input_key_count": len(raw),
                "output_fingerprint": fingerprint(data),
                "reexecuted_schedule_fingerprint": fingerprint(executed_data),
                "raw_input_output_pair_matches_reexecution": pair_matches,
            },
        }

    try:
        exact = isinstance(cases, dict) and set(cases) == required
        base, downside, upside = (
            unpack(cases["base"]),
            unpack(cases["downside"]),
            unpack(cases["upside"]),
        )
        case_values = {"base": base, "downside": downside, "upside": upside}
        pair_contract = exact and all(
            value["pair_evidence"]["raw_input_output_pair_matches_reexecution"]
            for value in case_values.values()
        )
        ordered_metrics = ["revenue", "ebitda", "equity_value"]
        aggregate_ordering = [
            {
                "metric": metric,
                "downside_value": downside[metric],
                "base_value": base[metric],
                "upside_value": upside[metric],
                "passed": downside[metric] <= base[metric] + 0.000001
                and base[metric] <= upside[metric] + 0.000001,
            }
            for metric in ordered_metrics
        ]
        core = all(
            all(status["passed"] for status in case["integrity"].values())
            and case["finite"]
            for case in case_values.values()
        )
        ordering = all(item["passed"] for item in aggregate_ordering)
        liquidity = {
            name: {
                "revolver_draw_activated": case["draw_activated"],
                "optional_sweep_activated": case["sweep_activated"],
            }
            for name, case in case_values.items()
        }
        liquidity_branches_observed = any(
            item["revolver_draw_activated"] for item in liquidity.values()
        ) or any(item["optional_sweep_activated"] for item in liquidity.values())
        passed = pair_contract and core and ordering and liquidity_branches_observed
        evidence = {
            "exact_case_ids": sorted(cases),
            "raw_input_output_pair_contract_passed": pair_contract,
            "raw_input_output_pairs": {
                name: value["pair_evidence"] for name, value in case_values.items()
            },
            "numerical_stability_and_core_integrity_passed": core,
            "aggregate_case_ordering": aggregate_ordering,
            "liquidity_branch_activation": liquidity,
            "material_liquidity_branch_observed": liquidity_branches_observed,
            "metrics": {
                name: {
                    key: value[key]
                    for key in [
                        "revenue",
                        "ebitda",
                        "fcff",
                        "cash",
                        "debt",
                        "equity_value",
                    ]
                }
                for name, value in case_values.items()
            },
        }
    except (KeyError, StopIteration, TypeError, ValueError):
        passed = False
        evidence = {
            "reason": "exact backend-executed Base, Downside, and Upside raw-input/output pairs are required"
        }
    return {
        "checks": [
            {
                "id": "scenario_directionality",
                "passed": passed,
                "message": "Re-executes each supplied raw input against its supplied output for the exact three composite backend cases, then tests aggregate ordering, numerical stability, and observed liquidity branches without recreating overrides.",
                "evidence": evidence,
            }
        ]
    }
