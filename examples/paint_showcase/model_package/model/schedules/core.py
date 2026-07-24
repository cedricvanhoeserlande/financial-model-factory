def convergence_status(residual, tolerance):
    converged = residual <= tolerance
    return {
        "converged": converged,
        "status": "converged" if converged else "not_converged",
        "passed": converged,
    }


def run(inputs):
    years = ["Y1", "Y2", "Y3", "Y4", "Y5"]
    paint = []
    tools = []
    operations = []
    working_capital = []
    ppe = []
    financing = []
    income_statement = []
    cash_flow = []
    balance_sheet = []
    retained_earnings = []
    pu = inputs["paint_units"]
    pp = inputs["paint_price"]
    pc = inputs["paint_unit_cost"]
    po = inputs["paint_overhead"]
    tu = inputs["tools_units"]
    tp = inputs["tools_price"]
    tc = inputs["tools_unit_cost"]
    ts = inputs["tools_storage"]
    corporate = inputs["corporate_opex"]
    opening_revenue = pu * pp + tu * tp
    opening_cos = pu * pc + po + tu * tc + ts
    reported_nwc = (
        inputs["opening_receivables"]
        + inputs["opening_inventory"]
        - inputs["opening_payables"]
    )
    normalized_nwc = (
        opening_revenue * inputs["receivable_days"] / 365
        + opening_cos * inputs["inventory_days"] / 365
        - opening_cos * inputs["payable_days"] / 365
    )
    pools = [
        {
            "id": "opening",
            "gross": inputs["opening_ppe"],
            "net": inputs["opening_ppe"],
            "life": inputs["opening_ppe_life"],
            "age": 0,
            "original_basis": inputs["opening_ppe"],
        }
    ]
    cash = inputs["opening_cash"]
    term = inputs["opening_term_debt"]
    revolver = inputs["opening_revolver"]
    equity = inputs["opening_equity"]
    prior_nwc = normalized_nwc
    for i, year in enumerate(years):
        paint_revenue = pu * pp
        tools_revenue = tu * tp
        paint_variable = pu * pc
        tools_purchase = tu * tc
        paint_cos = paint_variable + po
        tools_cos = tools_purchase + ts
        revenue = paint_revenue + tools_revenue
        cost_of_sales = paint_cos + tools_cos
        ebitda = revenue - cost_of_sales - corporate
        ar = revenue * inputs["receivable_days"] / 365
        inventory = cost_of_sales * inputs["inventory_days"] / 365
        payables = cost_of_sales * inputs["payable_days"] / 365
        nwc = ar + inventory - payables
        normalization = reported_nwc - normalized_nwc if i == 0 else 0.0
        recurring = prior_nwc - nwc
        prior_nwc = nwc
        capex = inputs["capex"][i]
        if capex > 0:
            pools.append(
                {
                    "id": "capex_" + str(i + 1),
                    "gross": capex,
                    "net": capex,
                    "life": inputs["new_capex_life"],
                    "age": 0,
                    "original_basis": capex,
                }
            )
        snapshots = []
        depreciation = 0.0
        retirement_gross = 0.0
        retirement_accumulated_depreciation = 0.0
        for pool in pools:
            opening_gross = pool["gross"]
            opening_net = pool["net"]
            opening_accumulated = opening_gross - opening_net
            fully_depreciated_availability = (
                opening_gross if opening_net <= 0.0000001 else 0.0
            )
            retired_gross = fully_depreciated_availability * inputs["disposal_rate"]
            retired_accumulated = retired_gross
            closing_gross = opening_gross - retired_gross
            closing_accumulated_before_dep = opening_accumulated - retired_accumulated
            convention = 0.5 if pool["age"] == 0 and pool["id"] != "opening" else 1.0
            annual_charge = pool["original_basis"] / pool["life"]
            dep = min(opening_net, annual_charge * convention)
            closing_net = opening_net - dep
            closing_accumulated = closing_accumulated_before_dep + dep
            snapshots.append(
                {
                    "id": pool["id"],
                    "opening_gross": opening_gross,
                    "opening_accumulated_depreciation": opening_accumulated,
                    "opening_net": opening_net,
                    "pre_retirement_net_book_value": opening_net,
                    "fully_depreciated_retirement_availability": fully_depreciated_availability,
                    "capex": capex if pool["id"] == "capex_" + str(i + 1) else 0.0,
                    "retirement_gross_cost": retired_gross,
                    "retirement_accumulated_depreciation": retired_accumulated,
                    "disposals": retired_gross,
                    "depreciation": dep,
                    "closing_gross": closing_gross,
                    "closing_accumulated_depreciation": closing_accumulated,
                    "closing_net": closing_net,
                }
            )
            pool["gross"] = closing_gross
            pool["net"] = closing_net
            pool["age"] += 1
            depreciation += dep
            retirement_gross += retired_gross
            retirement_accumulated_depreciation += retired_accumulated
        net_ppe = sum(pool["net"] for pool in pools)
        ebit = ebitda - depreciation
        guess_cash = cash
        guess_term = term
        guess_revolver = revolver
        tolerance = 0.0001
        residual = 0.0
        iteration = 0
        for iteration in range(1, 101):
            interest_expense = inputs["debt_interest_rate"] * (
                (term + revolver + guess_term + guess_revolver) / 2
            )
            qualifying_cash = (
                max(cash - inputs["minimum_cash"], 0.0)
                + max(guess_cash - inputs["minimum_cash"], 0.0)
            ) / 2
            interest_income = inputs["cash_interest_rate"] * qualifying_cash
            pretax = ebit - interest_expense + interest_income
            taxes = max(pretax, 0.0) * inputs["tax_rate"]
            net_income = pretax - taxes
            mandatory = min(inputs["mandatory_amortization"], term)
            pre_financing_cash = (
                cash
                + net_income
                + depreciation
                + recurring
                + normalization
                - capex
                - mandatory
            )
            available_term = term - mandatory
            if pre_financing_cash < inputs["minimum_cash"]:
                revolver_draw = inputs["minimum_cash"] - pre_financing_cash
                revolver_sweep = 0.0
                term_sweep = 0.0
                sweep_capacity = 0.0
                closing_cash = inputs["minimum_cash"]
                closing_revolver = revolver + revolver_draw
                closing_term = available_term
            else:
                revolver_draw = 0.0
                sweep_capacity = (pre_financing_cash - inputs["minimum_cash"]) * inputs[
                    "cash_sweep_pct"
                ]
                revolver_sweep = min(sweep_capacity, revolver)
                term_sweep = min(sweep_capacity - revolver_sweep, available_term)
                closing_revolver = revolver - revolver_sweep
                closing_term = available_term - term_sweep
                closing_cash = pre_financing_cash - revolver_sweep - term_sweep
            residual = max(
                abs(closing_cash - guess_cash),
                abs(closing_term - guess_term),
                abs(closing_revolver - guess_revolver),
            )
            guess_cash = closing_cash
            guess_term = closing_term
            guess_revolver = closing_revolver
            if convergence_status(residual, tolerance)["converged"]:
                break
        equity_close = equity + net_income
        operating_cash_flow = net_income + depreciation + recurring + normalization
        financing_cash_flow = -mandatory + revolver_draw - revolver_sweep - term_sweep
        net_change_cash = operating_cash_flow - capex + financing_cash_flow
        total_assets = closing_cash + ar + inventory + net_ppe
        total_liabilities_equity = (
            payables
            + inputs["opening_other_liabilities"]
            + closing_term
            + closing_revolver
            + equity_close
        )
        applied = i - 1
        paint.append(
            {
                "year": year,
                "units": pu,
                "unit_growth": None if i == 0 else inputs["paint_unit_growth"][applied],
                "price": pp,
                "price_inflation": (
                    None if i == 0 else inputs["paint_price_inflation"][applied]
                ),
                "unit_cost": pc,
                "unit_cost_inflation": (
                    None if i == 0 else inputs["paint_cost_inflation"][applied]
                ),
                "overhead": po,
                "overhead_inflation": (
                    None if i == 0 else inputs["paint_overhead_inflation"][applied]
                ),
                "revenue": paint_revenue,
                "revenue_per_unit": paint_revenue / pu if pu else None,
                "variable_cost": paint_variable,
                "variable_cost_per_unit": paint_variable / pu if pu else None,
                "gross_profit": paint_revenue - paint_cos,
                "gross_profit_per_unit": (
                    (paint_revenue - paint_cos) / pu if pu else None
                ),
                "gross_margin": (
                    (paint_revenue - paint_cos) / paint_revenue
                    if paint_revenue
                    else None
                ),
            }
        )
        tools.append(
            {
                "year": year,
                "units": tu,
                "unit_growth": None if i == 0 else inputs["tools_unit_growth"][applied],
                "price": tp,
                "price_inflation": (
                    None if i == 0 else inputs["tools_price_inflation"][applied]
                ),
                "unit_cost": tc,
                "unit_cost_inflation": (
                    None if i == 0 else inputs["tools_cost_inflation"][applied]
                ),
                "storage": ts,
                "storage_inflation": (
                    None if i == 0 else inputs["tools_storage_inflation"][applied]
                ),
                "revenue": tools_revenue,
                "revenue_per_unit": tools_revenue / tu if tu else None,
                "purchase_cost": tools_purchase,
                "purchase_cost_per_unit": tools_purchase / tu if tu else None,
                "gross_profit": tools_revenue - tools_cos,
                "gross_profit_per_unit": (
                    (tools_revenue - tools_cos) / tu if tu else None
                ),
                "gross_margin": (
                    (tools_revenue - tools_cos) / tools_revenue
                    if tools_revenue
                    else None
                ),
            }
        )
        operations.append(
            {
                "year": year,
                "revenue": revenue,
                "cost_of_sales": cost_of_sales,
                "gross_profit": revenue - cost_of_sales,
                "gross_margin": (
                    (revenue - cost_of_sales) / revenue if revenue else None
                ),
                "corporate_opex": corporate,
                "corporate_opex_inflation": (
                    None if i == 0 else inputs["corporate_opex_inflation"][applied]
                ),
                "ebitda": ebitda,
                "ebitda_margin": ebitda / revenue if revenue else None,
                "ebit": ebit,
            }
        )
        working_capital.append(
            {
                "year": year,
                "receivables": ar,
                "inventory": inventory,
                "payables": payables,
                "nwc": nwc,
                "recurring_cash_flow": recurring,
                "normalization_cash_flow": normalization,
            }
        )
        ppe.append(
            {
                "year": year,
                "pools": snapshots,
                "capex": capex,
                "retirement_gross_cost": retirement_gross,
                "retirement_accumulated_depreciation": retirement_accumulated_depreciation,
                "disposals": retirement_gross,
                "depreciation": depreciation,
                "closing_net_ppe": net_ppe,
            }
        )
        financing.append(
            {
                "year": year,
                "opening_cash": cash,
                "closing_cash": closing_cash,
                "opening_term_debt": term,
                "closing_term_debt": closing_term,
                "opening_revolver": revolver,
                "closing_revolver": closing_revolver,
                "mandatory_amortization": mandatory,
                "revolver_draw": revolver_draw,
                "revolver_sweep": revolver_sweep,
                "term_sweep": term_sweep,
                "sweep_capacity": sweep_capacity,
                "pre_financing_cash": pre_financing_cash,
                "interest_expense": interest_expense,
                "interest_income": interest_income,
                "qualifying_average_cash": qualifying_cash,
                "iterations": iteration,
                "convergence_residual": residual,
                "convergence_tolerance": tolerance,
                "converged": convergence_status(residual, tolerance)["converged"],
                "convergence_status": convergence_status(residual, tolerance)["status"],
            }
        )
        income_statement.append(
            {
                "year": year,
                "revenue": revenue,
                "cost_of_sales": cost_of_sales,
                "gross_profit": revenue - cost_of_sales,
                "operating_expenses": corporate,
                "ebitda": ebitda,
                "depreciation": depreciation,
                "ebit": ebit,
                "interest_expense": interest_expense,
                "interest_income": interest_income,
                "pretax_income": pretax,
                "taxes": taxes,
                "net_income": net_income,
            }
        )
        cash_flow.append(
            {
                "year": year,
                "net_income": net_income,
                "depreciation": depreciation,
                "recurring_working_capital": recurring,
                "normalization_working_capital": normalization,
                "operating_cash_flow": operating_cash_flow,
                "capex": capex,
                "investing_cash_flow": -capex,
                "mandatory_amortization": -mandatory,
                "revolver_draw": revolver_draw,
                "revolver_sweep": -revolver_sweep,
                "term_sweep": -term_sweep,
                "financing_cash_flow": financing_cash_flow,
                "net_change_cash": net_change_cash,
                "beginning_cash": cash,
                "ending_cash": closing_cash,
                "cash_reconciliation_residual": closing_cash - (cash + net_change_cash),
            }
        )
        balance_sheet.append(
            {
                "year": year,
                "cash": closing_cash,
                "receivables": ar,
                "inventory": inventory,
                "net_ppe": net_ppe,
                "total_assets": total_assets,
                "payables": payables,
                "other_current_liabilities": inputs["opening_other_liabilities"],
                "term_debt": closing_term,
                "revolver": closing_revolver,
                "equity": equity_close,
                "total_liabilities_equity": total_liabilities_equity,
                "balance_sheet_check": total_assets - total_liabilities_equity,
            }
        )
        retained_earnings.append(
            {
                "year": year,
                "opening_equity": equity,
                "net_income": net_income,
                "closing_equity": equity_close,
            }
        )
        cash = closing_cash
        term = closing_term
        revolver = closing_revolver
        equity = equity_close
        if i < 4:
            pu *= 1 + inputs["paint_unit_growth"][i]
            pp *= 1 + inputs["paint_price_inflation"][i]
            pc *= 1 + inputs["paint_cost_inflation"][i]
            po *= 1 + inputs["paint_overhead_inflation"][i]
            tu *= 1 + inputs["tools_unit_growth"][i]
            tp *= 1 + inputs["tools_price_inflation"][i]
            tc *= 1 + inputs["tools_cost_inflation"][i]
            ts *= 1 + inputs["tools_storage_inflation"][i]
            corporate *= 1 + inputs["corporate_opex_inflation"][i]
    fcff = []
    for i in range(5):
        operating_tax = max(operations[i]["ebit"], 0.0) * inputs["tax_rate"]
        value = (
            operations[i]["ebit"]
            - operating_tax
            + ppe[i]["depreciation"]
            - ppe[i]["capex"]
            + working_capital[i]["recurring_cash_flow"]
            + working_capital[i]["normalization_cash_flow"]
        )
        discount_factor = 1 / (1 + inputs["wacc"]) ** (i + 1)
        fcff.append(
            {
                "year": years[i],
                "operating_tax": operating_tax,
                "fcff": value,
                "discount_factor": discount_factor,
                "present_value": value * discount_factor,
            }
        )
    terminal_ebitda = operations[-1]["ebitda"]
    terminal_value = terminal_ebitda * inputs["exit_multiple"]
    terminal_discount_factor = 1 / (1 + inputs["wacc"]) ** 5
    terminal_present_value = terminal_value * terminal_discount_factor
    enterprise_value = (
        sum(item["present_value"] for item in fcff) + terminal_present_value
    )
    opening_net_debt = (
        inputs["opening_term_debt"]
        + inputs["opening_revolver"]
        - inputs["opening_cash"]
    )
    equity_value = enterprise_value - opening_net_debt
    sensitivity = []
    for multiple in [5.0, 5.5, 6.0, 6.5, 7.0]:
        values = []
        for rate in [0.07, 0.08, 0.09, 0.10, 0.11]:
            coordinate_enterprise_value = (
                sum(fcff[j]["fcff"] / (1 + rate) ** (j + 1) for j in range(5))
                + terminal_ebitda * multiple / (1 + rate) ** 5
            )
            values.append(coordinate_enterprise_value - opening_net_debt)
        sensitivity.append({"exit_multiple": multiple, "values": values})
    sensitivity_wacc_rates = [0.07, 0.08, 0.09, 0.10, 0.11]
    sensitivity_wacc_changes = [
        [row["values"][column + 1] - row["values"][column] for column in range(4)]
        for row in sensitivity
    ]
    wacc_direction_rounding_tolerance = 0.000001
    conventional_wacc_direction_supported = (
        all(row["fcff"] >= -wacc_direction_rounding_tolerance for row in fcff)
        and terminal_ebitda >= -wacc_direction_rounding_tolerance
    )
    wacc_non_increasing = all(
        change <= wacc_direction_rounding_tolerance
        for row in sensitivity_wacc_changes
        for change in row
    )
    if conventional_wacc_direction_supported:
        wacc_direction_status = (
            "conventional_non_increasing_verified"
            if wacc_non_increasing
            else "conventional_non_increasing_failed"
        )
        wacc_direction_warning = (
            None
            if wacc_non_increasing
            else "WACC sensitivity has a materially positive adjacent movement above the EUR 0.000001 rounding tolerance despite an all-non-negative FCFF and terminal-EBITDA profile."
        )
    elif any(
        change > wacc_direction_rounding_tolerance
        for row in sensitivity_wacc_changes
        for change in row
    ):
        wacc_direction_status = "non_monotonic_signed_fcff_warning"
        wacc_direction_warning = "Higher WACC increases one or more sensitivity values by more than the EUR 0.000001 rounding tolerance because negative forecast FCFF is discounted more heavily; conventional non-increasing WACC direction is not applicable."
    else:
        wacc_direction_status = "signed_fcff_nonconventional_non_increasing"
        wacc_direction_warning = "Forecast FCFF includes negative periods, so conventional WACC monotonicity is not asserted even though the displayed sensitivity values are non-increasing."
    term_rollforward_residuals = [
        item["closing_term_debt"]
        - (
            item["opening_term_debt"]
            - item["mandatory_amortization"]
            - item["term_sweep"]
        )
        for item in financing
    ]
    revolver_rollforward_residuals = [
        item["closing_revolver"]
        - (item["opening_revolver"] + item["revolver_draw"] - item["revolver_sweep"])
        for item in financing
    ]
    mandatory_cap_statuses = [
        item["mandatory_amortization"] <= item["opening_term_debt"] + 0.02
        for item in financing
    ]
    repayment_availability_statuses = [
        item["revolver_sweep"] <= item["opening_revolver"] + 0.02
        and item["term_sweep"]
        <= item["opening_term_debt"] - item["mandatory_amortization"] + 0.02
        for item in financing
    ]
    revolver_first_statuses = [
        item["term_sweep"]
        <= max(
            item["sweep_capacity"]
            - min(item["sweep_capacity"], item["opening_revolver"]),
            0.0,
        )
        + 0.02
        for item in financing
    ]
    draw_sweep_residuals = [
        item["revolver_draw"] * (item["revolver_sweep"] + item["term_sweep"])
        for item in financing
    ]
    debt_nonnegative_statuses = [
        item["closing_term_debt"] >= -0.02 and item["closing_revolver"] >= -0.02
        for item in financing
    ]
    ppe_rollforward_residuals = [
        item["closing_net_ppe"]
        - sum(pool["opening_net"] - pool["depreciation"] for pool in item["pools"])
        for item in ppe
    ]
    integrity_status = {
        "balance_sheet": {
            "residuals": [item["balance_sheet_check"] for item in balance_sheet],
            "passed": all(
                abs(item["balance_sheet_check"]) <= 0.02 for item in balance_sheet
            ),
        },
        "cash_flow": {
            "residuals": [item["cash_reconciliation_residual"] for item in cash_flow],
            "passed": all(
                abs(item["cash_reconciliation_residual"]) <= 0.02 for item in cash_flow
            ),
        },
        "debt_sweep": {
            "term_rollforward_residuals": term_rollforward_residuals,
            "revolver_rollforward_residuals": revolver_rollforward_residuals,
            "mandatory_amortization_cap_statuses": mandatory_cap_statuses,
            "repayment_availability_statuses": repayment_availability_statuses,
            "revolver_first_allocation_statuses": revolver_first_statuses,
            "draw_sweep_exclusivity_residuals": draw_sweep_residuals,
            "debt_nonnegative_statuses": debt_nonnegative_statuses,
            "passed": all(
                abs(x) <= 0.02
                for x in term_rollforward_residuals
                + revolver_rollforward_residuals
                + draw_sweep_residuals
            )
            and all(
                mandatory_cap_statuses
                + repayment_availability_statuses
                + revolver_first_statuses
                + debt_nonnegative_statuses
            ),
        },
        "ppe": {
            "residuals": [
                item["closing_net_ppe"]
                - sum(pool["closing_net"] for pool in item["pools"])
                for item in ppe
            ],
            "active_basis_rollforward_residuals": ppe_rollforward_residuals,
            "passed": all(
                abs(
                    item["closing_net_ppe"]
                    - sum(pool["closing_net"] for pool in item["pools"])
                )
                <= 0.02
                for item in ppe
            )
            and all(abs(x) <= 0.02 for x in ppe_rollforward_residuals),
        },
        "retained_earnings": {
            "residuals": [
                item["closing_equity"] - item["opening_equity"] - item["net_income"]
                for item in retained_earnings
            ],
            "passed": all(
                abs(
                    item["closing_equity"] - item["opening_equity"] - item["net_income"]
                )
                <= 0.02
                for item in retained_earnings
            ),
        },
        "minimum_cash": {
            "headroom": [
                item["closing_cash"] - inputs["minimum_cash"] for item in financing
            ],
            "compliance_statuses": [
                item["closing_cash"] >= inputs["minimum_cash"] - 0.02
                for item in financing
            ],
            "passed": all(
                item["closing_cash"] >= inputs["minimum_cash"] - 0.02
                for item in financing
            ),
        },
        "interest_convergence": {
            "residuals": [item["convergence_residual"] for item in financing],
            "statuses": [item["converged"] for item in financing],
            "maximum_convergence_residual": max(
                item["convergence_residual"] for item in financing
            ),
            "passed": all(item["converged"] for item in financing),
        },
        "enterprise_to_equity_bridge": {
            "residual": equity_value
            - (
                enterprise_value
                + inputs["opening_cash"]
                - inputs["opening_term_debt"]
                - inputs["opening_revolver"]
            ),
            "opening_cash": inputs["opening_cash"],
            "opening_term_debt": inputs["opening_term_debt"],
            "opening_revolver": inputs["opening_revolver"],
            "passed": abs(
                equity_value
                - (
                    enterprise_value
                    + inputs["opening_cash"]
                    - inputs["opening_term_debt"]
                    - inputs["opening_revolver"]
                )
            )
            <= 0.02,
        },
    }
    return {
        "periods": years,
        "paint": paint,
        "tools": tools,
        "operations": operations,
        "working_capital": working_capital,
        "opening_working_capital": {
            "reported_nwc": reported_nwc,
            "normalized_nwc": normalized_nwc,
            "normalization_cash_flow": reported_nwc - normalized_nwc,
        },
        "ppe": ppe,
        "financing": financing,
        "income_statement": income_statement,
        "cash_flow": cash_flow,
        "balance_sheet": balance_sheet,
        "retained_earnings": retained_earnings,
        "fcff": fcff,
        "valuation": {
            "terminal_ebitda": terminal_ebitda,
            "exit_multiple": inputs["exit_multiple"],
            "terminal_value": terminal_value,
            "terminal_discount_factor": terminal_discount_factor,
            "terminal_present_value": terminal_present_value,
            "enterprise_value": enterprise_value,
            "opening_cash": inputs["opening_cash"],
            "opening_term_debt": inputs["opening_term_debt"],
            "opening_revolver": inputs["opening_revolver"],
            "opening_net_debt": opening_net_debt,
            "terminal_cash": cash,
            "terminal_term_debt": term,
            "terminal_revolver": revolver,
            "terminal_total_debt": term + revolver,
            "net_debt": term + revolver - cash,
            "equity_value": equity_value,
            "sensitivity_value_type": "equity_value",
            "sensitivity": sensitivity,
            "sensitivity_wacc_rates": sensitivity_wacc_rates,
            "sensitivity_wacc_adjacent_changes": sensitivity_wacc_changes,
            "wacc_direction_rounding_tolerance": wacc_direction_rounding_tolerance,
            "signed_fcff_profile": [row["fcff"] for row in fcff],
            "conventional_wacc_direction_supported": conventional_wacc_direction_supported,
            "wacc_direction_status": wacc_direction_status,
            "wacc_direction_warning": wacc_direction_warning,
        },
        "integrity_status": integrity_status,
    }
