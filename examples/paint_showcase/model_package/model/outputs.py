def build_output(inputs, schedules):
    valuation = schedules["valuation"]
    last_operations = schedules["operations"][-1]
    last_income_statement = schedules["income_statement"][-1]
    last_balance_sheet = schedules["balance_sheet"][-1]
    integrity = schedules["integrity_status"]
    summary = {
        "current_case_only": True,
        "period": schedules["periods"][-1],
        "valuation_date": "opening_date",
        "year_5_revenue": last_operations["revenue"],
        "year_5_ebitda": last_operations["ebitda"],
        "year_5_ebitda_margin": last_operations["ebitda_margin"],
        "year_5_ebit": last_income_statement["ebit"],
        "year_5_net_income": last_income_statement["net_income"],
        "ending_cash": last_balance_sheet["cash"],
        "ending_term_debt": valuation["terminal_term_debt"],
        "ending_revolver": valuation["terminal_revolver"],
        "ending_total_debt": valuation["terminal_total_debt"],
        "net_debt": valuation["net_debt"],
        "enterprise_value": valuation["enterprise_value"],
        "opening_date_equity_value": valuation["equity_value"],
        "terminal_present_value_contribution": valuation["terminal_present_value"],
        "integrity_pass_statuses": {
            key: value["passed"] for key, value in integrity.items()
        },
        "maximum_interest_convergence_residual": integrity["interest_convergence"][
            "maximum_convergence_residual"
        ],
    }
    blocks = [
        {
            "id": "executive_summary",
            "type": "custom",
            "label": "Current-Case Executive Summary",
            "data": summary,
        },
        {
            "id": "performance_trend",
            "type": "time_series",
            "label": "Revenue and EBITDA",
            "data": {
                "x": schedules["periods"],
                "series": [
                    {
                        "id": "revenue",
                        "label": "Revenue",
                        "values": [row["revenue"] for row in schedules["operations"]],
                    },
                    {
                        "id": "ebitda",
                        "label": "EBITDA",
                        "values": [row["ebitda"] for row in schedules["operations"]],
                    },
                ],
            },
        },
        {
            "id": "income_statement",
            "type": "table",
            "label": "Income Statement",
            "data": {
                "columns": [
                    {"id": "year", "label": "Year"},
                    {"id": "revenue", "label": "Revenue"},
                    {"id": "ebitda", "label": "EBITDA"},
                    {"id": "ebit", "label": "EBIT"},
                    {"id": "net_income", "label": "Net Income"},
                ],
                "rows": schedules["income_statement"],
            },
        },
        {
            "id": "financial_model",
            "type": "custom",
            "label": "Integrated Financial Schedules",
            "data": schedules,
        },
        {
            "id": "current_case_integrity_status",
            "type": "custom",
            "label": "Current-Case Integrity Status",
            "data": integrity,
        },
        {
            "id": "valuation",
            "type": "custom",
            "label": "Exit Multiple DCF and Enterprise-to-Equity Bridge",
            "data": {
                "enterprise_value": valuation["enterprise_value"],
                "terminal_ebitda": valuation["terminal_ebitda"],
                "exit_multiple": valuation["exit_multiple"],
                "terminal_value": valuation["terminal_value"],
                "terminal_discount_factor": valuation["terminal_discount_factor"],
                "terminal_present_value": valuation["terminal_present_value"],
                "opening_cash": valuation["opening_cash"],
                "opening_term_debt": valuation["opening_term_debt"],
                "opening_revolver": valuation["opening_revolver"],
                "opening_net_debt": valuation["opening_net_debt"],
                "equity_value": valuation["equity_value"],
                "equity_value_valuation_date": "opening_date",
                "terminal_cash_reference_metric": valuation["terminal_cash"],
                "terminal_debt_reference_metric": valuation["terminal_total_debt"],
                "terminal_net_debt_reference_metric": valuation["net_debt"],
                "sensitivity_value_type": valuation["sensitivity_value_type"],
                "sensitivity": valuation["sensitivity"],
                "signed_fcff_profile": valuation["signed_fcff_profile"],
                "conventional_wacc_direction_supported": valuation[
                    "conventional_wacc_direction_supported"
                ],
                "wacc_direction_status": valuation["wacc_direction_status"],
                "wacc_direction_warning": valuation["wacc_direction_warning"],
                "sensitivity_wacc_adjacent_changes": valuation[
                    "sensitivity_wacc_adjacent_changes"
                ],
                "wacc_direction_rounding_tolerance_eur": valuation[
                    "wacc_direction_rounding_tolerance"
                ],
                "year_5_revenue": last_operations["revenue"],
                "year_5_ebitda": last_operations["ebitda"],
                "ending_cash": last_balance_sheet["cash"],
            },
        },
    ]
    return {
        "output_version": "2026-05-25",
        "output_blocks": blocks,
        "dashboard_spec": {
            "title": "Atelier Coatings & Tools S.A.",
            "sections": [
                "Performance overview",
                "Cash generation and leverage",
                "Working capital and investment",
                "Valuation",
            ],
        },
        "metadata": {"openai_called": False},
    }
