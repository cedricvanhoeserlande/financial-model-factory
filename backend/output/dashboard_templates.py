from __future__ import annotations


# Presentation grammar only. These records deliberately contain no equations,
# company assumptions, KPI values, or model-specific finance logic.
DASHBOARD_TEMPLATE_CATALOG = {
    "executive_finance": {
        "purpose": "Executive overview with headline KPIs followed by the most decision-useful trends.",
        "preferred_visuals": ["kpi", "combo", "waterfall", "table"],
        "layout": "KPI row first; two-column analytical grid; full-width detail last.",
    },
    "three_statement": {
        "purpose": "Linked statement presentation with readable line items and year columns.",
        "preferred_visuals": ["statement", "combo", "table"],
        "layout": "Full-width statements; supporting trends may sit in two columns.",
    },
    "revenue_profitability": {
        "purpose": "Revenue build, mix, gross profit, EBITDA and margin development.",
        "preferred_visuals": ["combo", "bar", "line", "table"],
        "layout": "Operating trends above detailed segment or bridge tables.",
    },
    "cash_liquidity": {
        "purpose": "Cash sources and uses with ending cash or liquidity overlaid as a line.",
        "preferred_visuals": ["combo", "waterfall", "kpi", "table"],
        "layout": "Liquidity KPIs first; cash movement chart; schedules below.",
    },
    "dcf_valuation": {
        "purpose": "Valuation summary, enterprise-to-equity bridge, and assumption sensitivities.",
        "preferred_visuals": ["kpi", "waterfall", "heatmap", "tornado"],
        "layout": "Valuation KPIs and bridge first; sensitivity analysis full width.",
    },
    "sensitivity": {
        "purpose": "Two-dimensional sensitivity and ranked one-variable impact analysis.",
        "preferred_visuals": ["heatmap", "tornado", "table"],
        "layout": "Full-width analytical visuals with compact assumption context.",
    },
}
