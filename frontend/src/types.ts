export type AppMode = "home" | "development" | "regular";
export type ActiveTab = "inputs" | "model" | "results" | "checks";

export type Account = {
  account_id: string;
  name: string;
};

export type ModelManifest = {
  version: string;
  account_id: string;
  model_id: string;
  name: string;
  description: string;
  status: "draft" | "published";
  scope_approved: boolean;
  build_ids: string[];
  version_ids: string[];
  current_version_id: string | null;
  canonical_version_id: string | null;
  current_version_state: string;
  published_utc?: string | null;
  created_utc: string;
  updated_utc: string;
  current_build_id: string | null;
  latest_run_id: string | null;
  current_input_params: InputParams;
  latest_validation_state: string;
  latest_stress_state: string;
  publish_eligible: boolean;
  publish_blocker: string;
  artifact_kind?: string;
  scope_summary: {
    agent: string;
    summary: string;
    questions: string[];
    approved_utc?: string;
    user_notes?: string;
  };
};

export type InputParams = Record<string, unknown>;

export type InputReviewItem = {
  key: string;
  path?: string;
  label?: string;
  group?: string;
  type?: string;
  unit?: string;
  storage_scale?: string;
  display_scale?: string;
  min_value?: number | null;
  max_value?: number | null;
  period_count?: number;
  period_labels?: string[];
  stress_values?: number[];
  required_for_publish?: boolean;
  out_of_domain_behavior?: string;
  read_only?: boolean;
  editable?: boolean;
  formula?: string;
  input_role?: "operating_driver" | "timeline_control" | "display_only" | "implied" | string;
  provenance?: "provided" | "required" | "inferred" | "defaulted" | "missing" | string;
  value?: unknown;
  assumed_value?: unknown;
  reason?: string;
  source?: string;
};

export type InputReviewSummary = {
  input_schema?: {
    groups?: { id: string; label: string }[];
    fields?: InputReviewItem[];
    compiler?: { strategy?: string; review_required?: boolean };
  };
  canonical_inputs?: InputReviewItem[];
  missing_inputs?: InputReviewItem[];
  ambiguous_inputs?: InputReviewItem[];
  inferred_inputs?: InputReviewItem[];
};

export type WorkflowState = {
  current_stage: string;
  next_required: string;
  run_type: string;
  draft_status: string;
  validation_passed?: boolean;
  stress_passed?: boolean;
  stages?: { id: string; label: string; state: string }[];
  change_classification?: {
    type: string;
    reason?: string;
    changed_inputs?: string[];
  };
};

export type UsageReport = {
  model: string;
  usage_summary: {
    input_tokens: number;
    cached_input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    reasoning_tokens?: number;
  };
  cost_summary: {
    estimated_cost_usd?: number;
    pricing_note?: string;
  };
};

export type GeneratedModel = {
  id: string;
  label: string;
  path?: string;
  source: string;
  plan: {
    title: string;
    steps?: string[];
    assumptions?: string[];
  };
  build_metadata: {
    run_id?: string;
    mode?: string;
    model?: string | null;
    model_id?: string | null;
    model_name?: string | null;
    openai_called?: boolean;
    draft_status?: string;
    workflow_state?: WorkflowState;
    input_review_summary?: InputReviewSummary;
    usage_report?: UsageReport;
    openai_state?: OpenAIState;
  };
};

export type ModelBuildSummary = {
  run_id: string;
  label: string;
  created_utc?: string;
  mode?: string;
  model?: string | null;
  openai_called: boolean;
  run_type?: string;
  draft_status?: string;
  prompt_preview?: string;
  is_latest?: boolean;
  usage_report?: UsageReport;
};

export type ResultRow = {
  section?: string;
  Section?: string;
  line?: string;
  Line?: string;
  values?: Record<string, number>;
  Year?: number | string;
  Value?: number;
};

export type OutputBlock =
  | {
      id: string;
      type: "kpi";
      label: string;
      data: { value: unknown; unit?: string; [key: string]: unknown };
    }
  | {
      id: string;
      type: "table";
      label: string;
      data: {
        columns: { id: string; label: string; [key: string]: unknown }[];
        rows: Record<string, unknown>[];
        [key: string]: unknown;
      };
    }
  | {
      id: string;
      type: "time_series";
      label: string;
      data: {
        x: (string | number)[];
        series: { id: string; label: string; values: number[]; [key: string]: unknown }[];
        [key: string]: unknown;
      };
    }
  | {
      id: string;
      type: "scenario_comparison";
      label: string;
      data: {
        scenarios: { id: string; label: string; [key: string]: unknown }[];
        metrics: { id: string; label: string; values: Record<string, unknown>; [key: string]: unknown }[];
        [key: string]: unknown;
      };
    }
  | {
      id: string;
      type: "custom";
      label: string;
      data: Record<string, unknown>;
    };

export type ModelResult = {
  output_version?: string;
  output_blocks?: OutputBlock[];
  dashboard_spec?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type CheckSummary = {
  passed: boolean;
  passed_checks?: number;
  total_checks?: number;
  checks?: { id: string; label: string; passed: boolean; details?: unknown }[];
  cases?: { id?: string; case_id?: string; label?: string; passed: boolean; details?: unknown }[];
};

export type DashboardWidget = {
  id: string;
  block_id: string;
  component: "kpi" | "chart" | "table" | "text";
  visual: "kpi" | "line" | "bar" | "combo" | "heatmap" | "tornado" | "waterfall" | "statement" | "table" | "text";
  columns: number;
  rows: number;
  options?: Record<string, unknown>;
};

export type DashboardSection = {
  id: string;
  title: string;
  widgets: DashboardWidget[];
};

export type DashboardSpecV2 = {
  version: "2.0";
  template_id: string;
  title: string;
  subtitle: string;
  currency: string;
  display_units: string;
  sections: DashboardSection[];
};

export type RerunExecutionEvidence = {
  canonical_version_id?: string | null;
  saved_entrypoint?: string | null;
  usage_ledger_count_before?: number;
  usage_ledger_count_after?: number;
  openai_call_delta?: number;
  openai_called?: boolean;
  inputs_changed?: boolean;
  output_changed?: boolean;
  validation_passed?: boolean;
  passed?: boolean;
};

export type RunPayload = {
  run_id: string;
  build_run_id: string;
  input_params: InputParams;
  model: GeneratedModel;
  result: ModelResult;
  validation_summary: CheckSummary;
  workflow_state: WorkflowState;
  input_review_summary: InputReviewSummary;
  metadata?: Record<string, unknown>;
  model_manifest?: ModelManifest;
  openai?: OpenAIState;
  rerun_execution_evidence?: RerunExecutionEvidence;
};

export type OpenAIState = {
  openai_mode: "unit_stub" | "live";
  may_call_openai: boolean;
  configured_model: string;
  api_key_configured: boolean;
};

export type ChatMessage = {
  role: "assistant" | "user";
  content: string;
  created_utc?: string;
};

export type InputAgentConversation = {
  messages: ChatMessage[];
  ready_to_draft: boolean;
  ready_to_spec?: boolean;
  scope_summary_version?: number;
  scope_summary?: string;
  locked_decisions?: string[];
  editable_placeholders?: string[];
  open_questions?: string[];
  last_scope_update_utc?: string;
  updated_utc?: string;
  model_name?: string;
  last_usage_report?: UsageReport | null;
};

export type ActionState = {
  can_rebuild: boolean;
  rebuild_reason: string;
  can_rerun: boolean;
  rerun_reason: string;
  can_reload_latest: boolean;
  reload_latest_reason: string;
  can_publish: boolean;
  publish_reason: string;
  can_open_regular: boolean;
  open_regular_reason: string;
};

export type PackageArtifact = {
  path: string;
  size?: number;
  kind?: string;
  content?: unknown;
};

export type PackageState = {
  version_id: string | null;
  canonical_version_id: string | null;
  status: string;
  status_label: string;
  stages: { id: string; label: string; state: string }[];
  human_review_required: boolean;
  publish_eligible: boolean;
  artifact_root: string;
  artifact_tree: PackageArtifact[];
  selected_artifact: PackageArtifact | null;
  input_schema: Record<string, unknown>;
  build_source?: string;
  published_rerun_uses_saved_package?: boolean;
  rerun_execution_evidence?: RerunExecutionEvidence;
  latest_run_status?: string;
  runtime_contract_defect?: Record<string, unknown> | null;
  compiler_manifest: Record<string, unknown>;
  source_provenance: Record<string, unknown>;
  model_spec?: Record<string, unknown>;
  model_spec_status?: string;
  model_spec_path?: string;
  model_spec_approval?: Record<string, unknown>;
  model_thesis?: Record<string, unknown>;
  model_thesis_status?: string;
  model_thesis_path?: string;
  equation_graph?: Record<string, unknown>;
  equation_graph_status?: string;
  equation_graph_path?: string;
  model_tests?: Record<string, unknown>[];
  model_tests_status?: string;
  model_tests_path?: string;
  model_tests_report?: Record<string, unknown>;
  agent_tool_calls_report?: Record<string, unknown>;
  package_files?: string[];
  amendment_status?: string;
  amendment_count?: number;
  previous_version_id?: string;
  change_summary?: Record<string, unknown>;
  pre_publish_summary?: Record<string, unknown>;
  validation_report: CheckSummary | Record<string, unknown>;
  mechanical_stress_report?: CheckSummary | Record<string, unknown>;
  modeler_self_check?: Record<string, unknown>;
  presentation_agent_report?: Record<string, unknown>;
  review_report?: Record<string, unknown>;
  review_history?: { repairs_used?: number; status?: string; rounds?: Record<string, unknown>[] };
  review_execution_evidence?: Record<string, unknown>;
  required_amendments_report?: Record<string, unknown>;
  repair_plan?: Record<string, unknown>;
  failure_report?: Record<string, unknown>;
  failure_code?: string;
  failure_subcode?: string;
  failure_stage?: string;
  failure_reasons?: string[];
  next_actions?: string[];
  review_failure_reasons?: string[];
  latest_output: ModelResult | Record<string, unknown>;
  openai_calls: Record<string, unknown>[];
  package_entrypoint: string;
  resolved_input_params?: InputParams;
};

export type WorkspacePayload = {
  workspace: {
    id: string;
    name: string;
    company?: string;
    seeded?: boolean;
    description?: string;
  };
  scenario: {
    id: string;
    name: string;
    description: string;
    horizon_years: number[];
    assumptions: InputParams;
  };
  account: Account;
  selected_model: ModelManifest | null;
  canonical_inputs: InputParams;
  input_review_summary: InputReviewSummary;
  workflow_state: WorkflowState;
  model: GeneratedModel;
  model_library: ModelBuildSummary[];
  model_library_lazy?: {
    loaded: boolean;
    endpoint: string;
  };
  latest_run: RunPayload | null;
  action_state: ActionState;
  openai: OpenAIState;
  package_state: PackageState;
  input_agent_conversation: InputAgentConversation;
  review_agent_conversation?: InputAgentConversation;
};

export type ModelsPayload = {
  account: Account;
  models: ModelManifest[];
  openai?: OpenAIState;
};

export type ModelActionPayload = ModelsPayload & {
  model_manifest: ModelManifest;
  workspace: WorkspacePayload;
  package_state?: PackageState;
};

export type BuildPayload = {
  run_id: string;
  input_params: InputParams;
  input_review_summary: InputReviewSummary;
  workflow_state: WorkflowState;
  model: GeneratedModel;
  model_manifest?: ModelManifest;
  openai?: OpenAIState;
};
