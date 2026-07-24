import type {
  CheckSummary,
  InputAgentConversation,
  InputParams,
  InputReviewItem,
  InputReviewSummary,
  ModelManifest,
  PackageState,
  ResultRow
} from "../types";

export type DevPhase = "scope_chat" | "input_review" | "building" | "review";
export type StepState = "pending" | "running" | "complete" | "failed" | "skipped";
export type BuildStep = { id: string; label: string; state: StepState };
export type NormalizedRow = { section: string; line: string; values: Record<string, number> };

export const BUILD_STEPS: BuildStep[] = [
  { id: "prompt", label: "Reading prompt", state: "pending" },
  { id: "openai", label: "Generating package files", state: "pending" },
  { id: "package", label: "Writing Python package", state: "pending" },
  { id: "execute", label: "Executing model", state: "pending" },
  { id: "validate", label: "Running package checks", state: "pending" },
  { id: "review", label: "Preparing review", state: "pending" }
];

const INPUT_LABELS: Record<string, string> = {
  revenue_2025: "Revenue 2025",
  revenue_growth: "Revenue growth",
  cogs_pct: "COGS %",
  sgna_pct: "SG&A %",
  tax_rate: "Tax rate",
  capex_pct: "Capex %",
  depreciation_rate: "Depreciation rate",
  cash_opening_2025: "Opening cash 2025",
  ppe_opening_2025: "Opening PP&E 2025",
  ar_opening_2025: "Opening AR 2025",
  inv_opening_2025: "Opening inventory 2025",
  ap_opening_2025: "Opening AP 2025",
  dso: "DSO days",
  dio: "DIO days",
  dpo: "DPO days",
  cff: "Financing cash flow",
  horizon_years: "Horizon years"
};

export function phaseForPackageState(packageState: PackageState): DevPhase {
  if (["review_ready", "failed_checks", "published"].includes(packageState.status)) return "review";
  return "scope_chat";
}

export function resetBuildSteps(): BuildStep[] {
  return BUILD_STEPS.map((step) => ({ ...step, state: "pending" }));
}

export function userConversationText(conversation: InputAgentConversation): string {
  return conversation.messages
    .filter((message) => message.role === "user")
    .map((message) => message.content.trim())
    .filter(Boolean)
    .join("\n\n");
}

export function formatTimeHorizon(value: unknown): string {
  if (!value || typeof value !== "object") return "";
  const row = value as Record<string, unknown>;
  return [row.start_year, row.end_year, row.granularity].filter(Boolean).join(" - ");
}

export function normalizeRows(rows: ResultRow[] | { rows?: ResultRow[] } | unknown): NormalizedRow[] {
  const sourceRows = Array.isArray(rows)
    ? rows
    : rows && typeof rows === "object" && Array.isArray((rows as { rows?: unknown }).rows)
      ? (rows as { rows: ResultRow[] }).rows
      : [];
  const grouped = new Map<string, NormalizedRow>();
  for (const row of sourceRows) {
    const raw = row as ResultRow & { statement?: string; line_item?: string; values_by_period?: Record<string, number> };
    const section = String(raw.section || raw.Section || raw.statement || "");
    const line = String(raw.line || raw.Line || raw.line_item || "");
    if (!section || !line) continue;
    const key = `${section}:${line}`;
    const existing = grouped.get(key) || { section, line, values: {} };
    const values = raw.values || raw.values_by_period;
    if (values && typeof values === "object") {
      for (const [year, value] of Object.entries(values)) existing.values[String(year)] = Number(value);
    } else if (raw.Year != null) {
      existing.values[String(raw.Year)] = Number(raw.Value || 0);
    }
    grouped.set(key, existing);
  }
  return Array.from(grouped.values());
}

export function isCustomModelInputs(_inputs: InputParams, inputReview: InputReviewSummary): boolean {
  const strategy = inputReview.input_schema?.compiler?.strategy;
  const hasSchemaDrivenFields = Boolean(inputReview.input_schema?.fields?.some((field) => String(field.path || field.key || "").includes(".")));
  return Boolean(strategy === "model_package" || hasSchemaDrivenFields);
}

export function getByPath(root: Record<string, unknown>, path: string): unknown {
  let current: unknown = root;
  for (const part of path.split(".")) {
    if (Array.isArray(current)) current = current[Number(part)];
    else if (current && typeof current === "object") current = (current as Record<string, unknown>)[part];
    else return undefined;
  }
  return current;
}

export function setByPath(root: Record<string, unknown>, path: string, value: unknown): Record<string, unknown> {
  const parts = path.split(".").filter(Boolean);
  if (!parts.length) return root;

  function cloneBranch(current: unknown, index: number): unknown {
    const part = parts[index];
    const isLeaf = index === parts.length - 1;
    if (Array.isArray(current)) {
      const copy = current.slice();
      const arrayIndex = Number(part);
      copy[arrayIndex] = isLeaf ? value : cloneBranch(copy[arrayIndex], index + 1);
      return copy;
    }
    const source = current && typeof current === "object" ? current as Record<string, unknown> : {};
    const copy: Record<string, unknown> = { ...source };
    copy[part] = isLeaf ? value : cloneBranch(copy[part], index + 1);
    return copy;
  }

  return cloneBranch(root, 0) as Record<string, unknown>;
}

export function latestRowsByScenario(rows: Record<string, unknown>[]): Record<string, unknown>[] {
  const byScenario = new Map<string, Record<string, unknown>>();
  rows.forEach((row) => byScenario.set(String(row.Scenario || "Base"), row));
  return Array.from(byScenario.values());
}

export function formatCell(value: unknown): string {
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (Array.isArray(value)) return value.map((item) => formatCell(item)).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return String(value ?? "");
}

export function friendlyLabel(value: string): string {
  return titleCase(value.replace(/_/g, " "));
}

export type InputParseResult =
  | { ok: true; value: number | string | number[] }
  | { ok: false; error: string };

export function parseInputValue(original: unknown, rawValue: string, field?: InputReviewItem): InputParseResult {
  const scheduleCount = field?.type === "number_or_13_number_array" ? 13 : field?.type === "number_or_number_array" ? Number(field.period_count) : 0;
  if (scheduleCount > 0 && rawValue.includes(",")) {
    const parts = rawValue.split(",").map((item) => item.trim());
    const cadence = field?.type === "number_or_13_number_array" ? "weekly" : "period";
    if (parts.length !== scheduleCount) return {
      ok: false,
      error: field?.type === "number_or_13_number_array" ? "Enter exactly 13 weekly values." : `Enter exactly ${scheduleCount} ${cadence} values.`
    };
    if (parts.some((item) => item === "")) return { ok: false, error: "Every period requires a value." };
    const parsed = parts.map((item) => Number(item));
    if (!parsed.every((item) => Number.isFinite(item))) return { ok: false, error: "Every schedule value must be a finite number." };
    const stored = parsed.map((item) => toStoredInputNumber(item, field));
    const boundsError = inputBoundsError(stored, field);
    return boundsError ? { ok: false, error: boundsError } : { ok: true, value: stored };
  }
  if (Array.isArray(original)) {
    const parsed = rawValue.split(",").map((item) => Number(item.trim()));
    if (!parsed.every((item) => Number.isFinite(item))) return { ok: false, error: "Enter only finite numeric values." };
    return { ok: true, value: parsed };
  }
  if (typeof original === "number") {
    if (rawValue.trim() === "") return { ok: false, error: "A numeric value is required." };
    const parsed = Number(rawValue);
    if (!Number.isFinite(parsed)) return { ok: false, error: "Enter a finite number." };
    const stored = toStoredInputNumber(parsed, field);
    const boundsError = inputBoundsError([stored], field);
    return boundsError ? { ok: false, error: boundsError } : { ok: true, value: stored };
  }
  return { ok: true, value: rawValue };
}

export function inputValue(value: unknown, field?: InputReviewItem): string {
  if (Array.isArray(value)) return value.map((item) => inputValue(item, field)).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (typeof value === "number" && field?.unit === "percent" && field.storage_scale === "decimal" && field.display_scale === "percent") {
    return formatInputNumber(value * 100);
  }
  if (typeof value === "number") return formatInputNumber(value);
  return String(value ?? "");
}

function toStoredInputNumber(value: number, field?: InputReviewItem): number {
  return field?.unit === "percent" && field.storage_scale === "decimal" && field.display_scale === "percent"
    ? value / 100
    : value;
}

function inputBoundsError(values: number[], field?: InputReviewItem): string {
  if (typeof field?.min_value === "number" && values.some((value) => value < field.min_value!)) {
    return `Value must be at least ${inputValue(field.min_value, field)}.`;
  }
  if (typeof field?.max_value === "number" && values.some((value) => value > field.max_value!)) {
    return `Value must be at most ${inputValue(field.max_value, field)}.`;
  }
  return "";
}

function formatInputNumber(value: number): string {
  const normalized = Math.abs(value) < 1e-9 ? 0 : value;
  return normalized.toFixed(2).replace(/\.?0+$/, "");
}

export function inputLabel(key: string): string {
  return INPUT_LABELS[key] || titleCase(key.replace(/_/g, " "));
}

export function titleCase(value: string): string {
  return value.replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}

export function formatModelStatus(model: ModelManifest): string {
  if (model.status === "published" && model.latest_validation_state === "passed") return "Published";
  if (model.status === "published") return "Published";
  if (model.latest_validation_state === "passed") return "Draft / Passed";
  return "Draft";
}

export function reportPassed(report: CheckSummary | Record<string, unknown>): boolean {
  return Boolean(report && typeof report === "object" && "passed" in report && report.passed === true);
}

export function cleanSpecText(value: string): string {
  return value
    .split(/\r?\n/)
    .filter((line) => !/^\s*(assistant|user)\s*:/i.test(line))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function formatSpecValue(value: string): string {
  return value
    .replace(/cogs_pct/gi, "COGS %")
    .replace(/sgna_pct/gi, "SG&A %")
    .replace(/revenue_growth/gi, "Revenue growth")
    .replace(/horizon_years/gi, "Horizon years")
    .replace(/\bkpis\b/gi, "KPIs")
    .replace(/chart_series/gi, "chart series")
    .replace(/_/g, " ");
}

export function isNoisyArtifact(path: string): boolean {
  return path.includes("__pycache__") || /\.(pyc|pyo)$/i.test(path);
}

export function formatCheckLabel(value?: string): string {
  if (!value) return "Check";
  return formatSpecValue(value)
    .replace(/\bup\b/i, "up")
    .replace(/\bdown\b/i, "down")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/^\w/, (letter) => letter.toUpperCase());
}

export function formatNumber(value: number): string {
  const numeric = Number(value || 0);
  const maximumFractionDigits = Number.isInteger(numeric) ? 0 : Math.abs(numeric) < 1 ? 6 : 2;
  return numeric.toLocaleString(undefined, { maximumFractionDigits });
}
