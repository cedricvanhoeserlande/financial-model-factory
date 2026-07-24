# Manual model verification record

Verified package: `version_20260721_005747_33fedf06`

Verification date: 2026-07-21

## Result

The package is internally reconciled for the stated synthetic scope and reruns locally from saved Python code. This verification is not audit, transaction or investment assurance.

## Executed reconciliation checks

- FY1 uses the submitted starting units and prices; growth applies only across the four subsequent annual transitions.
- Paint and tools revenue reconcile to units multiplied by price, and segment costs reconcile to the declared unit-cost and overhead policies.
- Each forecast balance sheet satisfies assets equal liabilities plus equity.
- Cash-flow statements reconcile beginning cash, operating, investing and financing flows to ending cash.
- Retained earnings reconcile opening equity plus net income to closing equity.
- Term debt and revolver roll-forwards reconcile; mandatory amortization is capped; draws and sweeps are mutually exclusive.
- Debt interest uses average total debt and cash interest uses average excess cash above minimum cash.
- Minimum-cash, revolver-draw and excess-cash-sweep branches were exercised, including a binding liquidity case.
- Working-capital normalization appears once in FY1 and does not recur in FY2-FY5.
- PP&E pools reconcile to closing net PP&E, including opening-pool life, half-year capex depreciation and the declared disposal convention.
- FCFF excludes financing income and expense and reconciles to EBIT after tax, depreciation, capex and working-capital cash requirements.
- Discounted forecast FCFF plus discounted terminal value reconciles to enterprise value.
- Opening cash and opening debt bridge enterprise value to opening-date equity value.
- A balanced opening structure different from EUR 20m assets and 50% leverage executes without invalidating reusable checks.
- Legal zero-valued operating, tax, WACC and terminal-multiple inputs remain finite and zero-safe.
- The saved package's model-local checks pass, with Base-only calibration honestly reported as not applicable for changed cases rather than falsely passed.

Verification result: 8 of 8 finance test groups passed.

After acceptance, Black 26.5.1 mechanically formatted the seven generated Python files for source-preview readability. Four files changed formatting and three were already compliant. The canonical combined output-and-check hash remained `3de7a23546b92b67d64b42d00ea579b9fd81b3fe223fa0b44a5d9ff2649e684e` before and after formatting.

## Recorded review findings

The final `gpt-5.6-luna` Review Agent approved the package after deterministic admission. Its remaining findings were advisory:

- terminal present value represents approximately 69% of enterprise value, so valuation remains sensitive to Year 5 EBITDA and the exit multiple;
- the Downside composite case reaches binding minimum-cash headroom and draws the revolver, while Base and Upside do not.

## Material limitations

- Annual timing does not capture seasonality or intra-year liquidity.
- No covenants, leases, pensions, acquisitions, minority interests or advanced tax accounting are modeled.
- Disposals are simplified zero-net-book-value retirements with no proceeds, gains, losses or impairment.
- The DCF uses only an exit-multiple terminal value and no perpetuity-growth method.
- The opening-date enterprise-to-equity bridge uses opening cash and debt; terminal financing balances are reference information only.

Technical checks passed; business review required.
