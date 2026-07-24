import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts";
import { loadPaintShowcase, paintShowcaseArchiveUrl, readPaintShowcaseFile, rerunPaintShowcase, type PaintShowcaseFile } from "../api";

type ChartProps = { option: echarts.EChartsOption; className?: string; label: string };

function Chart({ option, className = "", label }: ChartProps) {
  const node = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!node.current) return;
    const chart = echarts.init(node.current, undefined, { renderer: "canvas" });
    chart.setOption({ ...option, animation: false });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    const observer = new ResizeObserver(resize);
    observer.observe(node.current);
    return () => { observer.disconnect(); window.removeEventListener("resize", resize); chart.dispose(); };
  }, [option]);
  return <div ref={node} className={`paint-chart ${className}`} role="img" aria-label={label} />;
}

const euro = (value: number, digits = 1) => value < 0 ? `(€${Math.abs(value).toFixed(digits)}m)` : `€${value.toFixed(digits)}m`;
const axis = { axisLine: { lineStyle: { color: "#dbe3e8" } }, axisTick: { show: false }, axisLabel: { color: "#6a7c89", formatter: (value: string | number) => typeof value === "number" && value < 0 ? `(${Math.abs(value)})` : String(value) } };
const tooltip = { trigger: "axis" as const, backgroundColor: "#102d3d", borderWidth: 0, textStyle: { color: "#fff" }, valueFormatter: (v: unknown) => typeof v === "number" ? euro(v, 2) : String(v) };

function Kpi({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return <article className={`paint-kpi ${accent ? "accent" : ""}`}><span>{label}</span><strong>{value}</strong></article>;
}

type CheckRow = { id: string; passed: boolean; status?: "passed" | "failed" | "skipped"; message: string; evidence?: unknown };

const checkStatus = (row: CheckRow): "passed" | "failed" | "skipped" => row.status ?? (row.passed ? "passed" : "failed");
const checksAcceptable = (rows: CheckRow[]): boolean => rows.length > 0 && rows.every(row => checkStatus(row) !== "failed");

function checkRows(value: Record<string, unknown> | null): CheckRow[] {
  const rows = value?.checks;
  if (!Array.isArray(rows)) return [];
  return rows.filter((row): row is CheckRow => Boolean(
    row && typeof row === "object" && typeof row.id === "string" &&
    typeof row.passed === "boolean" && typeof row.message === "string"
  ));
}

function checkTitle(id: string): string {
  return id.split("_").map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
}

function ChecksDialog({ checks, dirty, onClose }: { checks: Record<string, unknown> | null; dirty: boolean; onClose: () => void }) {
  const rows = checkRows(checks);
  const passed = rows.filter(row => checkStatus(row) === "passed").length;
  const skipped = rows.filter(row => checkStatus(row) === "skipped").length;
  const allPassed = checksAcceptable(rows);
  return <div className="paint-dialog-backdrop" role="presentation" onClick={onClose}>
    <section className="paint-checks-dialog" role="dialog" aria-modal="true" aria-labelledby="paint-checks-title" onClick={event => event.stopPropagation()}>
      <header><div><h2 id="paint-checks-title">Model checks</h2><p>Technical checks passed; business review required.</p></div><button aria-label="Close checks" onClick={onClose}>×</button></header>
      <div className="paint-checks-summary">
        <strong className={allPassed ? "passed" : "failed"}>{rows.length ? `${passed} passed${skipped ? ` · ${skipped} not applicable` : ""}` : "Checks unavailable"}</strong>
        <span className={dirty ? "stale" : "current"}>{dirty ? "Inputs changed · rerun required" : "Synced with current inputs"}</span>
      </div>
      <div className="paint-check-list">{rows.map(row => { const status = checkStatus(row); return <article className={status} key={row.id}>
        <div className="paint-check-status" aria-label={status === "skipped" ? "Not applicable" : status === "passed" ? "Passed" : "Failed"}>{status === "skipped" ? "N/A" : status === "passed" ? "✓" : "×"}</div>
        <div><h3>{checkTitle(row.id)}</h3><p>{row.message}</p>{row.evidence !== undefined ? <details><summary>Technical evidence</summary><pre>{JSON.stringify(row.evidence, null, 2)}</pre></details> : null}</div>
      </article>; })}</div>
    </section>
  </div>;
}

const pythonKeywords = new Set(["and", "as", "assert", "break", "class", "continue", "def", "del", "elif", "else", "except", "False", "finally", "for", "from", "if", "import", "in", "is", "lambda", "None", "not", "or", "pass", "raise", "return", "True", "try", "while", "with", "yield"]);

function PythonCode({ source }: { source: string }) {
  const tokenPattern = /(#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\b\d+(?:\.\d+)?\b|\b[A-Za-z_]\w*\b)/g;
  return <>{source.split("\n").map((line, lineIndex) => <span className="paint-code-line" key={lineIndex}>{line.split(tokenPattern).map((token, tokenIndex) => {
    const className = token.startsWith("#") ? "comment" : token.startsWith("\"") || token.startsWith("'") ? "string" : /^\d/.test(token) ? "number" : pythonKeywords.has(token) ? "keyword" : "";
    return <span className={className} key={tokenIndex}>{token}</span>;
  })}{"\n"}</span>)}</>;
}

function StatementTable({ statement, data }: { statement: "income" | "balance" | "cash" | "valuation"; data: any }) {
  const rows = statement === "income" ? [
    ["Revenue", data.income.revenue], ["COGS", data.income.cogs], ["Gross profit", data.income.grossProfit],
    ["Operating expenses", data.income.operatingExpenses], ["EBITDA", data.income.ebitda], ["D&A", data.income.depreciation],
    ["EBIT", data.income.ebit], ["Interest expense", data.income.interestExpense], ["Interest income", data.income.interestIncome],
    ["Earnings before tax", data.income.earningsBeforeTax], ["Taxes", data.income.taxes], ["Net income", data.income.netIncome]
  ] : statement === "balance" ? [
    ["Cash", data.balance.cash], ["Receivables", data.balance.receivables], ["Inventory", data.balance.inventory],
    ["Net PP&E", data.balance.netPpe], ["Total assets", data.balance.totalAssets],
    ["Accounts payable", data.balance.payables], ["Other current liabilities", data.balance.otherLiabilities],
    ["Term debt", data.balance.termDebt], ["Revolver", data.balance.revolver], ["Total debt", data.balance.debt],
    ["Total liabilities", data.balance.debt.map((debt: number, i: number) => debt + data.balance.payables[i] + data.balance.otherLiabilities[i])],
    ["Equity", data.balance.equity],
    ["Total liabilities & equity", data.balance.debt.map((debt: number, i: number) => debt + data.balance.payables[i] + data.balance.otherLiabilities[i] + data.balance.equity[i])]
  ] : [
    ["Net income", data.cashFlow.netIncome], ["D&A", data.cashFlow.depreciationAddBack],
    ["Recurring working-capital movement", data.cashFlow.recurringWorkingCapital], ["Working-capital normalization", data.cashFlow.normalization],
    ["Operating cash flow", data.cashFlow.operatingCashFlow], ["Capital expenditure", data.cashFlow.capex],
    ["Investing cash flow", data.cashFlow.investingCashFlow], ["Mandatory amortization", data.cashFlow.debtAmortization],
    ["Revolver draw", data.cashFlow.revolverDraw], ["Cash sweep", data.cashFlow.cashSweep],
    ["Financing cash flow", data.cashFlow.financingCashFlow], ["Net change in cash", data.cashFlow.netChange],
    ["Ending cash", data.cashFlow.endingCash]
  ];
  const valuationRows = [
    ["EBIT", data.valuation.ebit], ["Operating taxes", data.valuation.operatingTax], ["NOPAT", data.valuation.nopat],
    ["D&A", data.valuation.depreciationAddBack], ["Recurring working-capital movement", data.valuation.recurringWorkingCapital],
    ["Working-capital normalization", data.valuation.normalization], ["Capital expenditure", data.valuation.capex], ["FCFF", data.valuation.fcff]
  ];
  const totalLabels = new Set(["Revenue", "Gross profit", "EBITDA", "EBIT", "Earnings before tax", "Net income", "Total assets", "Total debt", "Total liabilities", "Total liabilities & equity", "Operating cash flow", "Investing cash flow", "Financing cash flow", "Net change in cash", "Ending cash"]);
  const visibleRows = statement === "valuation" ? valuationRows : rows;
  return <div className="paint-table-wrap"><table className="paint-statement"><thead><tr><th>EURm</th>{data.periods.map((p: string) => <th key={p}>{p}</th>)}</tr></thead><tbody>{visibleRows.map(([label, values]) => <tr key={String(label)} className={totalLabels.has(String(label)) || label === "NOPAT" || label === "FCFF" ? "total" : ""}><th>{label}</th>{(values as readonly number[]).map((v, i) => <td key={i}>{v < 0 ? `(${Math.abs(v).toFixed(1)})` : v.toFixed(1)}</td>)}</tr>)}</tbody></table></div>;
}

function getPath(source: Record<string, any>, path: string): unknown {
  return path.split(".").reduce<unknown>((value, key) => value && typeof value === "object" ? (value as Record<string, unknown>)[key] : undefined, source);
}

function setPath(source: Record<string, any>, path: string, value: number): Record<string, any> {
  const clone = structuredClone(source);
  const parts = path.split(".");
  let target = clone;
  parts.slice(0, -1).forEach(part => { target = target[part] as Record<string, any>; });
  target[parts[parts.length - 1]] = value;
  return clone;
}

function isPercentPath(path: string): boolean {
  return /(growth|inflation|_rate$|_pct$|(^|\.)wacc$)/.test(path);
}

function inputUnit(path: string): string {
  if (isPercentPath(path)) return "%";
  if (/_days$/.test(path)) return "days";
  if (/(?:terminal|exit)_multiple$/.test(path)) return "x";
  if (/(^|\.)[^.]*units$/.test(path)) return "units";
  if (/(^|\.)(paint|tools)_(price|unit_cost)$/.test(path) || /\.(price|unit_cost)$/.test(path)) return "EUR/unit";
  if (/(life)$/.test(path)) return "years";
  return "EURm";
}

function columns(rows: Array<Record<string, any>>, key: string): number[] {
  return rows.map(row => Number(row[key] ?? 0));
}

function dashboardFromOutput(output: Record<string, any>, inputs: Record<string, any>, limitations: string[] = []): any {
  const blocks = Array.isArray(output.output_blocks) ? output.output_blocks : [];
  const financialModel = blocks.find((block: any) => block.id === "financial_model")?.data;
  if (!financialModel) throw new Error("Accepted showcase package did not expose the required financial_model block.");
    const valuationBlock = blocks.find((block: any) => block.id === "valuation")?.data || financialModel.valuation;
    const income = financialModel.income_statement;
    const cashFlow = financialModel.cash_flow;
    const balance = financialModel.balance_sheet;
    const financing = financialModel.financing;
    const ppe = financialModel.ppe;
    const sensitivityRows = valuationBlock.sensitivity || [];
    const sensitivityIsEquity = valuationBlock.sensitivity_value_type === "equity_value";
    const waccValues = [0.07, 0.08, 0.09, 0.10, 0.11];
    const openingCash = Number(inputs.opening_cash ?? 0);
    const openingDebt = Number(inputs.opening_term_debt ?? 0) + Number(inputs.opening_revolver ?? 0);
    const openingNetDebt = openingDebt - openingCash;
    return {
      periods: financialModel.periods.map((period: string, index: number) => /^FY/i.test(period) ? period : `FY${index + 1}`),
      limitations,
      hero: {
        enterpriseValue: valuationBlock.enterprise_value / 1_000_000,
        equityValue: valuationBlock.equity_value / 1_000_000,
        year5Revenue: income[4].revenue / 1_000_000,
        year5Ebitda: income[4].ebitda / 1_000_000,
        year5EbitdaMargin: income[4].ebitda / income[4].revenue,
        year5Ufcf: financialModel.fcff[4].fcff / 1_000_000
      },
      income: {
        revenue: columns(income, "revenue").map(value => value / 1_000_000),
        grossProfit: columns(income, "gross_profit").map(value => value / 1_000_000),
        ebitda: columns(income, "ebitda").map(value => value / 1_000_000),
        ebit: columns(income, "ebit").map(value => value / 1_000_000),
        interestExpense: columns(income, "interest_expense").map(value => -value / 1_000_000),
        interestIncome: columns(income, "interest_income").map(value => value / 1_000_000),
        netIncome: columns(income, "net_income").map(value => value / 1_000_000),
        cogs: income.map((row: any) => (row.gross_profit - row.revenue) / 1_000_000),
        operatingExpenses: income.map((row: any) => (row.ebitda - row.gross_profit) / 1_000_000),
        depreciation: income.map((row: any) => (row.ebit - row.ebitda) / 1_000_000),
        earningsBeforeTax: income.map((row: any) => (row.ebit - row.interest_expense + row.interest_income) / 1_000_000),
        taxes: income.map((row: any) => (row.net_income - row.ebit + row.interest_expense - row.interest_income) / 1_000_000),
        ebitdaMargin: financialModel.operations.map((row: any) => row.ebitda_margin)
      },
      segments: {
        paintRevenue: columns(financialModel.paint, "revenue").map(value => value / 1_000_000),
        toolsRevenue: columns(financialModel.tools, "revenue").map(value => value / 1_000_000),
        paintGrossProfit: columns(financialModel.paint, "gross_profit").map(value => value / 1_000_000),
        toolsGrossProfit: columns(financialModel.tools, "gross_profit").map(value => value / 1_000_000)
      },
      cashFlow: {
        netIncome: columns(cashFlow, "net_income").map(value => value / 1_000_000),
        cfo: cashFlow.map((row: any) => (row.operating_cash_flow - row.normalization_working_capital) / 1_000_000),
        depreciationAddBack: columns(cashFlow, "depreciation").map(value => value / 1_000_000),
        recurringWorkingCapital: columns(cashFlow, "recurring_working_capital").map(value => value / 1_000_000),
        normalization: columns(cashFlow, "normalization_working_capital").map(value => value / 1_000_000),
        operatingCashFlow: columns(cashFlow, "operating_cash_flow").map(value => value / 1_000_000),
        capex: columns(cashFlow, "capex").map(value => -value / 1_000_000),
        investingCashFlow: columns(cashFlow, "capex").map(value => -value / 1_000_000),
        debtAmortization: columns(cashFlow, "mandatory_amortization").map(value => value / 1_000_000),
        revolverDraw: columns(cashFlow, "revolver_draw").map(value => value / 1_000_000),
        cashSweep: financing.map((row: any) => -(row.revolver_sweep + row.term_sweep) / 1_000_000),
        financingCashFlow: cashFlow.map((row: any, index: number) => (row.mandatory_amortization + row.revolver_draw - financing[index].revolver_sweep - financing[index].term_sweep) / 1_000_000),
        netChange: columns(cashFlow, "net_change_cash").map(value => value / 1_000_000),
        endingCash: columns(cashFlow, "ending_cash").map(value => value / 1_000_000),
        ufcf: columns(financialModel.fcff, "fcff").map(value => value / 1_000_000)
      },
      valuation: {
        ebit: columns(income, "ebit").map(value => value / 1_000_000),
        operatingTax: columns(financialModel.fcff, "operating_tax").map(value => -value / 1_000_000),
        nopat: financialModel.fcff.map((row: any, index: number) => (income[index].ebit - row.operating_tax) / 1_000_000),
        depreciationAddBack: columns(cashFlow, "depreciation").map(value => value / 1_000_000),
        recurringWorkingCapital: columns(cashFlow, "recurring_working_capital").map(value => value / 1_000_000),
        normalization: columns(cashFlow, "normalization_working_capital").map(value => value / 1_000_000),
        capex: columns(cashFlow, "capex").map(value => -value / 1_000_000),
        fcff: columns(financialModel.fcff, "fcff").map(value => value / 1_000_000)
      },
      balance: {
        cash: columns(balance, "cash").map(value => value / 1_000_000),
        receivables: columns(balance, "receivables").map(value => value / 1_000_000),
        inventory: columns(balance, "inventory").map(value => value / 1_000_000),
        netPpe: columns(balance, "net_ppe").map(value => value / 1_000_000),
        totalAssets: columns(balance, "total_assets").map(value => value / 1_000_000),
        payables: columns(balance, "payables").map(value => value / 1_000_000),
        otherLiabilities: columns(balance, "other_current_liabilities").map(value => value / 1_000_000),
        termDebt: columns(balance, "term_debt").map(value => value / 1_000_000),
        revolver: columns(balance, "revolver").map(value => value / 1_000_000),
        debt: balance.map((row: any) => (row.term_debt + row.revolver) / 1_000_000),
        equity: columns(balance, "equity").map(value => value / 1_000_000)
      },
      ppe: {
        capex: columns(ppe, "capex").map(value => value / 1_000_000),
        depreciation: columns(ppe, "depreciation").map(value => value / 1_000_000),
        disposals: columns(ppe, "disposals").map(value => value / 1_000_000)
      },
      dcf: {
        pvUfcf: columns(financialModel.fcff, "present_value").map(value => value / 1_000_000),
        pvForecastUfcf: columns(financialModel.fcff, "present_value").reduce((sum, value) => sum + value, 0) / 1_000_000,
        pvTerminal: valuationBlock.terminal_present_value / 1_000_000,
        enterpriseValue: valuationBlock.enterprise_value / 1_000_000,
        openingDebt: -openingDebt / 1_000_000,
        openingCash: openingCash / 1_000_000,
        equityValue: valuationBlock.equity_value / 1_000_000,
        wacc: Number(inputs.wacc ?? 0),
        exitMultiple: valuationBlock.exit_multiple
      },
      sensitivity: {
        wacc: waccValues.map(value => `${(value * 100).toFixed(0)}%`),
        multiple: sensitivityRows.map((row: any) => `${Number(row.exit_multiple).toFixed(1)}x`),
        values: waccValues.map((_wacc, waccIndex) => sensitivityRows.map((row: any) => (Number(row.values[waccIndex]) - (sensitivityIsEquity ? 0 : openingNetDebt)) / 1_000_000))
      }
    };
}

const keyInputPaths = ["paint_units", "paint_price", "paint_unit_cost", "tools_units", "tools_price", "wacc"];

const inputNumberFormatter = new Intl.NumberFormat("en-US", {
  useGrouping: true,
  maximumFractionDigits: 4,
});

function EditableNumber({ value, min, max, disabled = false, onChange, onValidityChange }: { value: number; min?: number; max?: number; disabled?: boolean; onChange: (value: number) => void; onValidityChange: (message: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));

  useEffect(() => {
    if (!editing) setDraft(String(value));
  }, [editing, value]);

  const commit = (text: string) => {
    const parsed = Number(text.replace(/[\s,]/g, ""));
    if (text.trim() === "" || !Number.isFinite(parsed)) {
      onValidityChange("Enter a finite number.");
      return;
    }
    if (min !== undefined && parsed < min) {
      onValidityChange(`Value must be at least ${inputNumberFormatter.format(min)}.`);
      return;
    }
    if (max !== undefined && parsed > max) {
      onValidityChange(`Value must be no more than ${inputNumberFormatter.format(max)}.`);
      return;
    }
    onValidityChange("");
    onChange(parsed);
  };

  return <input
    type="text"
    inputMode="decimal"
    value={editing ? draft : inputNumberFormatter.format(value)}
    disabled={disabled}
    aria-valuemin={min}
    aria-valuemax={max}
    onFocus={event => {
      setDraft(String(value));
      setEditing(true);
      event.currentTarget.select();
    }}
    onChange={event => {
      const next = event.target.value;
      setDraft(next);
      commit(next);
    }}
    onBlur={() => {
      commit(draft);
      setEditing(false);
    }}
  />;
}

function FieldEditor({ field, inputs, onChange, onValidityChange, error, compact = false }: { field: Record<string, any>; inputs: Record<string, any>; onChange: (path: string, value: number) => void; onValidityChange: (path: string, message: string) => void; error?: string; compact?: boolean }) {
  const path = String(field.path);
  const stored = getPath(inputs, path);
  const scalar = Array.isArray(stored) ? stored[0] : stored;
  const percent = isPercentPath(path);
  const millions = inputUnit(path) === "EURm";
  const displayScale = percent ? 100 : millions ? 1 / 1_000_000 : 1;
  const shown = typeof scalar === "number" ? scalar * displayScale : 0;
  const accentIndex = keyInputPaths.indexOf(path);
  const locked = /^opening(?:\.|_)/.test(path) && path !== "opening_ppe_life";
  return <label className={`${compact ? "paint-key-input" : "paint-field-row"} ${accentIndex >= 0 ? `key-${accentIndex}` : ""} ${locked ? "locked" : ""} ${error ? "invalid" : ""}`}>
    <span>{String(field.label || path)}</span>
    {compact ? <small>Synced</small> : null}
    <div><EditableNumber
      value={Number(shown.toFixed(4))}
      disabled={locked}
      min={typeof field.min_value === "number" ? field.min_value * displayScale : undefined}
      max={typeof field.max_value === "number" ? field.max_value * displayScale : undefined}
      onChange={value => onChange(path, value / displayScale)}
      onValidityChange={message => onValidityChange(path, message)}
    /><em>{inputUnit(path)}</em></div>
    {error ? <strong className="paint-field-error">{error}</strong> : null}
  </label>;
}

function InputWorkspace({ inputs, fields, errors, onChange, onValidityChange, onRerun, pending, status }: { inputs: Record<string, any>; fields: Array<Record<string, any>>; errors: Record<string, string>; onChange: (path: string, value: number) => void; onValidityChange: (path: string, message: string) => void; onRerun: () => void; pending: boolean; status: string }) {
  const visible = fields;
  const byPath = (patterns: RegExp[]) => visible.filter(field => patterns.some(pattern => pattern.test(String(field.path))));
  const groups = [
    { id: "revenues", title: "Revenues", fields: byPath([/^(paint|tools)_(units|price|unit_growth|price_inflation)$/]) },
    { id: "costs", title: "Costs & fixed assets", fields: byPath([/^(paint_unit_cost|paint_overhead|tools_unit_cost|tools_storage|corporate_opex)$/, /^(paint_cost|paint_overhead|tools_cost|tools_storage|corporate_opex)_inflation$/, /^(capex|opening_ppe_life|new_capex_life|disposal_rate)$/]) },
    { id: "working-capital", title: "Working capital", fields: byPath([/^opening_(cash|receivables|inventory|payables|other_liabilities)$/, /^(receivable_days|inventory_days|payable_days)$/]) },
    { id: "financing", title: "Financing & valuation", fields: byPath([/^opening_(ppe|term_debt|revolver|equity)$/, /^(minimum_cash|mandatory_amortization|debt_interest_rate|cash_interest_rate|cash_sweep_pct|tax_rate|wacc|exit_multiple)$/]) }
  ].filter(group => group.fields.length > 0);
  const keyFields = keyInputPaths.map(path => visible.find(field => String(field.path) === path)).filter((field): field is Record<string, any> => Boolean(field));
  return <section className="paint-workspace paint-input-workspace" data-testid="paint-input-tab">
    <div className="paint-workspace-heading"><div><h1>Input</h1></div><div className="paint-rerun-control"><button onClick={onRerun} disabled={pending || Object.keys(errors).length > 0}>{pending ? "Running…" : "Run model"}</button><small>{Object.keys(errors).length ? "Correct invalid inputs before rerunning" : status}</small></div></div>
    <div className="paint-key-inputs">{keyFields.map(field => <FieldEditor field={field} inputs={inputs} onChange={onChange} onValidityChange={onValidityChange} error={errors[String(field.path)]} compact key={String(field.path)} />)}</div>
    <div className="paint-input-groups">{groups.map(group => <article className="paint-input-group" key={group.id}><h2>{group.title}</h2><div>{group.fields.map(field => <FieldEditor field={field} inputs={inputs} onChange={onChange} onValidityChange={onValidityChange} error={errors[String(field.path)]} key={String(field.path)} />)}</div></article>)}</div>
  </section>;
}

function ModelWorkspace({ files, selected, content, onSelect }: { files: PaintShowcaseFile[]; selected: string; content: string; onSelect: (path: string) => void }) {
  const visibleFiles = files.filter(file => file.bytes > 0);
  const rootFiles = visibleFiles.filter(file => !file.path.replace(/^model\//, "").includes("/"));
  const scheduleFiles = visibleFiles.filter(file => file.path.replace(/^model\//, "").startsWith("schedules/"));
  const fileSize = (bytes: number) => bytes === 0 ? "0 KB" : bytes < 1024 ? "<1 KB" : `${Math.round(bytes / 1024)} KB`;
  const fileButton = (file: PaintShowcaseFile, nested = false) => <button className={`${selected === file.path ? "active" : ""} ${nested ? "nested" : ""}`} onClick={() => onSelect(file.path)} key={file.path}><span>{file.path.split("/").slice(-1)[0]}</span><small>{fileSize(file.bytes)}</small></button>;
  return <section className="paint-workspace paint-model-workspace" data-testid="paint-model-tab">
    <div className="paint-workspace-heading"><div><h1>Model</h1></div><a className="paint-download" href={paintShowcaseArchiveUrl} download>Download ZIP</a></div>
    <div className="paint-code-layout"><aside><div className="paint-tree-root">model</div>{rootFiles.map(file => fileButton(file))}{scheduleFiles.length ? <><div className="paint-tree-folder">schedules</div>{scheduleFiles.map(file => fileButton(file, true))}</> : null}</aside><article><header><span>{selected || "Select a source file"}</span><button disabled={!content} onClick={() => void navigator.clipboard.writeText(content)}>Copy code</button></header><pre><code>{selected ? content ? <PythonCode source={content} /> : "This file is intentionally empty." : "Choose a file from the generated package tree."}</code></pre></article></div>
  </section>;
}

export function PaintShowcase() {
  const [activeArea, setActiveArea] = useState<"input" | "model" | "output">("output");
  const [statement, setStatement] = useState<"income" | "balance" | "cash" | "valuation">("income");
  const [data, setData] = useState<any>(null);
  const [inputs, setInputs] = useState<Record<string, any>>({});
  const [fields, setFields] = useState<Array<Record<string, any>>>([]);
  const [files, setFiles] = useState<PaintShowcaseFile[]>([]);
  const [selectedFile, setSelectedFile] = useState("");
  const [fileContent, setFileContent] = useState("");
  const [rerunPending, setRerunPending] = useState(false);
  const [rerunStatus, setRerunStatus] = useState("Loading…");
  const [checks, setChecks] = useState<Record<string, unknown> | null>(null);
  const [checksDirty, setChecksDirty] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [showLimitations, setShowLimitations] = useState(false);
  const [showChecks, setShowChecks] = useState(false);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});
  useEffect(() => {
    const previousTitle = document.title;
    document.title = "Model Factory";
    return () => { document.title = previousTitle; };
  }, []);
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [activeArea]);
  useEffect(() => {
    void loadPaintShowcase().then(payload => {
      setInputs(payload.inputs);
      setFields(Array.isArray(payload.input_schema.fields) ? payload.input_schema.fields : []);
      setFiles(payload.model_files || []);
      setChecks(payload.checks);
      setChecksDirty(false);
      setData(dashboardFromOutput(payload.output, payload.inputs, Array.isArray(payload.limitations) ? payload.limitations : []));
      setRerunStatus("Ready");
    }).catch(error => {
      setWorkspaceError(error instanceof Error ? error.message : String(error));
      setRerunStatus("Package unavailable");
    });
  }, []);

  async function selectFile(path: string) {
    setSelectedFile(path);
    setFileContent("Loading source…");
    try {
      const payload = await readPaintShowcaseFile(path);
      setFileContent(payload.content);
    } catch (error) {
      setFileContent(error instanceof Error ? error.message : String(error));
    }
  }

  async function rerun() {
    if (Object.keys(inputErrors).length) {
      setRerunStatus("Correct invalid inputs before rerunning");
      return;
    }
    setRerunPending(true);
    setWorkspaceError("");
    setRerunStatus("Running…");
    try {
      const payload = await rerunPaintShowcase(inputs);
      setChecks(payload.checks);
      setChecksDirty(false);
      if (!payload.technical_checks_passed) throw new Error("The model executed, but its model-local finance checks did not all pass.");
      setData((previous: any) => dashboardFromOutput(payload.output, inputs, previous?.limitations || []));
      setRerunStatus("Updated locally");
      setActiveArea("output");
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setWorkspaceError(message);
      setRerunStatus("Rerun failed");
    } finally {
      setRerunPending(false);
    }
  }
  if (!data) {
    return <main className="paint-showcase"><header className="paint-topbar"><div className="paint-brand" aria-label="Model Factory"><span className="paint-brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="12" width="3" height="7" rx="1"/><rect x="10.5" y="8" width="3" height="11" rx="1"/><rect x="16" y="4" width="3" height="15" rx="1"/></svg></span><span className="paint-brand-name">Model Factory</span></div></header>{workspaceError ? <div className="paint-workspace-error">{workspaceError}</div> : <section className="paint-workspace"><div className="paint-loading-state">Loading accepted model package…</div></section>}</main>;
  }
  const revenueOption: echarts.EChartsOption = {
    color: ["#163f59", "#d7a93b"], tooltip, legend: { top: 0, textStyle: { color: "#667985" } }, grid: { left: 44, right: 24, top: 44, bottom: 32 },
    xAxis: { type: "category", data: [...data.periods], ...axis }, yAxis: { type: "value", ...axis },
    series: [
      { name: "Revenue", type: "bar", data: [...data.income.revenue], barWidth: 18, itemStyle: { borderRadius: 0 }, label: { show: true, position: "top", distance: 7, color: "#173f59", fontSize: 11, fontWeight: "bold", formatter: (p: any) => euro(p.value, 1) } },
      { name: "EBITDA", type: "bar", data: [...data.income.ebitda], barWidth: 18, barGap: "65%", itemStyle: { borderRadius: 0 }, label: { show: true, position: "top", distance: 7, color: "#8f6818", fontSize: 11, fontWeight: "bold", formatter: (p: any) => euro(p.value, 1) } }
    ]
  };
  const cashOption: echarts.EChartsOption = {
    color: ["#45a99d", "#d6a94a", "#d66b5f", "#173f59"], tooltip, legend: { top: 0, itemWidth: 14, itemHeight: 8, textStyle: { fontSize: 10 } }, grid: { left: 44, right: 46, top: 58, bottom: 32 },
    xAxis: { type: "category", data: [...data.periods], ...axis }, yAxis: { type: "value", ...axis },
    series: [
      { name: "Operating cash flow", type: "bar", stack: "flow", data: [...data.cashFlow.operatingCashFlow] },
      { name: "Investing cash flow", type: "bar", stack: "flow", data: [...data.cashFlow.investingCashFlow] },
      { name: "Financing cash flow", type: "bar", stack: "flow", data: [...data.cashFlow.financingCashFlow] },
      { name: "Ending cash", type: "line", data: [...data.cashFlow.endingCash], smooth: true, symbolSize: 7, lineStyle: { width: 3 }, label: { show: true, position: "top", distance: 8, color: "#173f59", fontWeight: "bold", formatter: (p: any) => euro(p.value, 1) } }
    ]
  };
  const segmentOption: echarts.EChartsOption = {
    color: ["#173f59", "#73c4ba", "#66899a", "#b8ded9"], tooltip, legend: { top: 0 }, grid: { left: 44, right: 24, top: 54, bottom: 32 },
    xAxis: { type: "category", data: [...data.periods], ...axis }, yAxis: { type: "value", ...axis },
    series: [
      { name: "Paint revenue", type: "bar", stack: "revenue", barWidth: 18, data: [...data.segments.paintRevenue] },
      { name: "Tools revenue", type: "bar", stack: "revenue", barWidth: 18, data: [...data.segments.toolsRevenue], label: { show: true, position: "top", distance: 7, color: "#173f59", fontSize: 11, fontWeight: "bold", formatter: (p: any) => euro(data.segments.paintRevenue[p.dataIndex] + data.segments.toolsRevenue[p.dataIndex], 1) } },
      { name: "Paint gross profit", type: "bar", stack: "gross-profit", barWidth: 18, barGap: "65%", data: [...data.segments.paintGrossProfit] },
      { name: "Tools gross profit", type: "bar", stack: "gross-profit", barWidth: 18, data: [...data.segments.toolsGrossProfit], label: { show: true, position: "top", distance: 7, color: "#4f6e7d", fontSize: 11, fontWeight: "bold", formatter: (p: any) => euro(data.segments.paintGrossProfit[p.dataIndex] + data.segments.toolsGrossProfit[p.dataIndex], 1) } }
    ]
  };
  const sensitivityValues = data.sensitivity.values.flat();
  const sensitivityMin = Math.min(...sensitivityValues);
  const sensitivityMax = Math.max(...sensitivityValues);
  const sensitivityData = data.sensitivity.values.flatMap((row: number[], y: number) => row.map((v: number, x: number) => ({ value: [x, y, v] })));
  const sensitivityOption: echarts.EChartsOption = {
    tooltip: { position: "top", backgroundColor: "#102d3d", borderWidth: 0, textStyle: { color: "#fff" }, formatter: (p: any) => `${data.sensitivity.wacc[p.value[1]]} WACC<br/>${data.sensitivity.multiple[p.value[0]]} exit multiple<br/><b>${euro(p.value[2], 2)} equity value</b>` },
    grid: { left: 58, right: 12, top: 12, bottom: 42 }, xAxis: { type: "category", data: [...data.sensitivity.multiple], ...axis }, yAxis: { type: "category", data: [...data.sensitivity.wacc], ...axis },
    visualMap: { min: sensitivityMin, max: sensitivityMax, show: false, inRange: { color: ["#eff5f5", "#d9ebe8", "#bddfd9", "#98cec7", "#73b9b2"] } },
    series: [{ type: "heatmap", data: sensitivityData, label: { show: true, color: "#12313f", fontWeight: "bold", formatter: (p: any) => p.value[2].toFixed(1) }, emphasis: { itemStyle: { shadowBlur: 8, shadowColor: "rgba(0,0,0,.18)" } } }]
  };
  const forecastValue = data.dcf.pvForecastUfcf;
  const enterpriseValue = data.dcf.enterpriseValue;
  const afterDebt = enterpriseValue + data.dcf.openingDebt;
  const dcfBridge = [forecastValue, data.dcf.pvTerminal, Math.abs(data.dcf.openingDebt), data.dcf.openingCash, data.dcf.equityValue];
  const dcfHelper = [0, forecastValue, afterDebt, afterDebt, 0];
  const bridgeConnectors = [
    [0, forecastValue],
    [1, enterpriseValue],
    [2, afterDebt],
    [3, data.dcf.equityValue]
  ];
  const dcfOption: echarts.EChartsOption = {
    tooltip: { trigger: "axis", axisPointer: { type: "shadow" }, formatter: (items: any) => { const item = items.find((entry: any) => entry.seriesName === "Bridge"); const signed = item.dataIndex === 2 ? -item.value : item.value; return `${item.name}<br/><b>${euro(signed, 2)}</b>`; } },
    grid: { left: 20, right: 20, top: 28, bottom: 46 }, xAxis: { type: "category", data: ["PV\nFCFF", "PV terminal\nvalue", "Debt", "Cash", "Equity\nvalue"], axisLine: { show: false }, axisTick: { show: false }, axisLabel: { color: "#6a7c89" } }, yAxis: { type: "value", show: false, splitLine: { show: false } },
    series: [
      { name: "Position", type: "bar", stack: "dcf", data: dcfHelper, silent: true, itemStyle: { color: "transparent" }, emphasis: { itemStyle: { color: "transparent" } } },
      {
        name: "Connector",
        type: "custom",
        coordinateSystem: "cartesian2d",
        silent: true,
        z: 1,
        data: bridgeConnectors,
        renderItem: (_params: any, api: any) => {
          const category = api.value(0);
          const level = api.value(1);
          const from = api.coord([category, level]);
          const to = api.coord([category + 1, level]);
          return {
            type: "line",
            shape: { x1: from[0] + 19, y1: from[1], x2: to[0] - 19, y2: to[1] },
            style: { stroke: "#9eafb7", lineWidth: 1 }
          };
        }
      } as any,
      { name: "Bridge", type: "bar", stack: "dcf", z: 2, data: dcfBridge.map((v, i) => { const barColor = i === 4 ? "#173f59" : i === 2 ? "#d66b5f" : i === 1 ? "#d8aa45" : "#47a99e"; return { value: v, itemStyle: { color: barColor, borderColor: barColor, borderWidth: 1, borderRadius: 0 }, label: { show: true, position: i === 2 ? "bottom" : "top", formatter: euro(i === 2 ? -v : v, 1), color: "#294654", fontWeight: "bold" } }; }), barWidth: 38 }
    ]
  };

  return <main className="paint-showcase">
    <header className="paint-topbar"><div className="paint-brand" aria-label="Model Factory"><span className="paint-brand-mark"><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="12" width="3" height="7" rx="1"/><rect x="10.5" y="8" width="3" height="11" rx="1"/><rect x="16" y="4" width="3" height="15" rx="1"/></svg></span><span className="paint-brand-name">Model Factory</span></div><nav className="paint-primary-tabs" aria-label="Showcase workspace">{(["input", "model", "output"] as const).map(area => <button key={area} className={activeArea === area ? "active" : ""} aria-selected={activeArea === area} onClick={() => setActiveArea(area)}>{area === "input" ? "Input" : area === "model" ? "Model" : "Output"}</button>)}</nav><div className="paint-more"><button aria-label="Showcase options" aria-expanded={menuOpen} onClick={() => setMenuOpen(value => !value)}>•••</button>{menuOpen ? <div role="menu"><button role="menuitem" onClick={() => { setShowChecks(true); setMenuOpen(false); }}>Checks</button><button role="menuitem" onClick={() => { setShowLimitations(true); setMenuOpen(false); }}>Model limitations</button></div> : null}</div></header>
    {workspaceError ? <div className="paint-workspace-error">{workspaceError}</div> : null}
    {activeArea === "input" ? <InputWorkspace inputs={inputs} fields={fields} errors={inputErrors} onChange={(path, value) => { setInputs(current => setPath(current, path, value)); setChecksDirty(true); }} onValidityChange={(path, message) => setInputErrors(current => { const next = { ...current }; if (message) next[path] = message; else delete next[path]; return next; })} onRerun={() => void rerun()} pending={rerunPending} status={rerunStatus} /> : activeArea === "model" ? <ModelWorkspace files={files} selected={selectedFile} content={fileContent} onSelect={path => void selectFile(path)} /> : <>
    <section className="paint-workspace paint-output-workspace"><div className="paint-workspace-heading"><div><h1>Output</h1></div><button className={`paint-check-indicator ${checksDirty ? "stale" : checksAcceptable(checkRows(checks)) ? "passed" : "failed"}`} onClick={() => setShowChecks(true)}>{checksDirty ? "Checks stale" : checksAcceptable(checkRows(checks)) ? "Checks passed" : "Checks failed"}</button></div></section>
    <section className="paint-kpi-grid" aria-label="Key performance indicators">
      <Kpi label="Equity value" value={euro(data.hero.equityValue)} accent />
      <Kpi label="Enterprise value" value={euro(data.hero.enterpriseValue)} />
      <Kpi label="FY5 revenue" value={euro(data.hero.year5Revenue)} />
      <Kpi label="FY5 EBITDA" value={euro(data.hero.year5Ebitda)} />
      <Kpi label="FY5 FCFF" value={euro(data.hero.year5Ufcf)} />
    </section>

    <section id="valuation" className="paint-section"><div className="paint-section-heading"><h2>Valuation</h2></div>
      <div className="paint-grid valuation"><article className="paint-card"><div className="paint-card-title"><h3>Equity value bridge</h3><span>EURm</span></div><Chart option={dcfOption} label="Enterprise to equity value bridge" /></article>
      <article className="paint-card"><div className="paint-card-title"><h3>WACC / exit multiple sensitivity</h3><span>Equity value · EURm</span></div><Chart option={sensitivityOption} label="Equity value sensitivity heatmap" /></article>
      </div>
    </section>

    <section id="statements" className="paint-section"><div className="paint-section-heading"><h2>Financial statements</h2></div>
      <div className="paint-grid two"><article className="paint-card wide"><div className="paint-card-title"><h3>Cash flows & ending balance</h3><span>EURm</span></div><Chart option={cashOption} label="Operating, investing and financing cash flow with ending cash" /><div className="paint-cash-reconciliation" aria-label="Net cash flow by year"><strong>Net CF</strong>{data.periods.map((period: string, index: number) => <span key={period} title={period}>{euro(data.cashFlow.netChange[index], 1)}</span>)}</div></article>
      <article className="paint-card statement-card"><div className="paint-card-title paint-statement-title"><h3>Financial statements</h3><div className="paint-segmented" role="tablist">{(["income", "balance", "cash", "valuation"] as const).map(item => <button role="tab" aria-selected={statement === item} className={statement === item ? "active" : ""} onClick={() => setStatement(item)} key={item}>{item === "income" ? "Income" : item === "balance" ? "Balance sheet" : item === "cash" ? "Cash flow" : "Valuation"}</button>)}</div></div><StatementTable statement={statement} data={data} /></article></div>
    </section>

    <section id="performance" className="paint-section"><div className="paint-section-heading"><h2>Operating performance</h2></div>
      <div className="paint-grid two"><article className="paint-card wide"><div className="paint-card-title"><h3>Revenue & EBITDA</h3><span>EURm</span></div><Chart option={revenueOption} label="Revenue and EBITDA over five years" /></article>
      <article className="paint-card"><div className="paint-card-title"><h3>Segment contribution</h3><span>EURm</span></div><Chart option={segmentOption} label="Paint and tools segment revenue and gross profit" /></article></div>
    </section>
    </>}
    {showChecks ? <ChecksDialog checks={checks} dirty={checksDirty} onClose={() => setShowChecks(false)} /> : null}
    {showLimitations ? <div className="paint-dialog-backdrop" role="presentation" onClick={() => setShowLimitations(false)}><section className="paint-limitations-dialog" role="dialog" aria-modal="true" aria-labelledby="paint-limitations-title" onClick={event => event.stopPropagation()}><header><h2 id="paint-limitations-title">Model limitations</h2><button aria-label="Close limitations" onClick={() => setShowLimitations(false)}>×</button></header><ul>{data.limitations.map((item: string) => <li key={item}>{item}</li>)}</ul></section></div> : null}
  </main>;
}
