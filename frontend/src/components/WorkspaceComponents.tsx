import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import * as echarts from "echarts";
import { packageArchiveUrl, readPackageArtifact } from "../api";
import type {
  ActiveTab,
  AppMode,
  ChatMessage,
  CheckSummary,
  DashboardSpecV2,
  DashboardWidget,
  InputAgentConversation,
  InputParams,
  InputReviewItem,
  InputReviewSummary,
  ModelManifest,
  ModelResult,
  OpenAIState,
  OutputBlock,
  PackageArtifact,
  PackageState,
  RunPayload
} from "../types";

export type ModelSetupState = {
  periodicity: string;
  startYear: string;
  startSubPeriod: string;
  horizon: string;
  currency: string;
  units: string;
};
import {
  type BuildStep,
  type DevPhase,
  formatCell,
  formatCheckLabel,
  formatModelStatus,
  friendlyLabel,
  getByPath,
  inputLabel,
  inputValue,
  isCustomModelInputs
} from "../utils/viewHelpers";

export function DevelopmentFlow({
  phase,
  model,
  conversation,
  reviewConversation,
  chatInput,
  setChatInput,
  reviewChatInput,
  setReviewChatInput,
  openai,
  packageState,
  latestRun,
  inputParams,
  inputReview,
  buildSteps,
  onSend,
  onSendReview,
  chatPending,
  reviewChatPending,
  onGenerateModelSpec,
  onApproveModelSpec,
  onBuildModelPackage,
  onAmendPackage,
  onPublish,
  onInputChange,
  amendmentPending,
}: {
  phase: DevPhase;
  model: ModelManifest | null;
  conversation: InputAgentConversation;
  reviewConversation: InputAgentConversation;
  chatInput: string;
  setChatInput: (value: string) => void;
  reviewChatInput: string;
  setReviewChatInput: (value: string) => void;
  openai: OpenAIState;
  packageState: PackageState;
  latestRun: RunPayload | null;
  inputParams: InputParams;
  inputReview: InputReviewSummary;
  buildSteps: BuildStep[];
  onSend: () => void;
  onSendReview: () => void;
  chatPending: boolean;
  reviewChatPending: boolean;
  onGenerateModelSpec: (prompt: string) => void;
  onApproveModelSpec: () => void;
  onBuildModelPackage: (prompt: string, openaiBacked?: boolean) => void;
  onAmendPackage: (message: string) => void;
  onPublish: () => void;
  onInputChange: (key: string, value: string) => void;
  amendmentPending: boolean;
}) {
  const scopeMode = phase === "scope_chat" || packageState.status === "not_started";
  return (
    <section className="development-grid unified-development-workspace" data-testid="development-flow">
      <section className="workflow-panel" data-testid="workflow-panel">
        {scopeMode ? (
          <ScopeWorkflowPanel
            conversation={conversation}
            openai={openai}
            packageState={packageState}
            chatInput={chatInput}
            onGenerateModelSpec={onGenerateModelSpec}
            onApproveModelSpec={onApproveModelSpec}
            onBuildModelPackage={onBuildModelPackage}
          />
        ) : null}
        {phase === "input_review" ? (
          <InputReviewPanel
            inputParams={inputParams}
            inputReview={inputReview}
            onInputChange={onInputChange}
          />
        ) : null}
        {phase === "building" ? <BuildProgressPanel steps={buildSteps} /> : null}
        {!scopeMode && phase !== "input_review" && phase !== "building" ? (
          <ReviewPanel
            latestRun={latestRun}
            model={model}
            packageState={packageState}
            inputParams={inputParams}
            inputReview={inputReview}
            buildSteps={buildSteps}
            openai={openai}
            onPublish={onPublish}
            onAmendPackage={onAmendPackage}
            onInputChange={onInputChange}
            amendmentPending={amendmentPending}
          />
        ) : null}
      </section>
      <AgentChatPane
        phase={phase}
        conversation={scopeMode ? conversation : reviewConversation}
        chatInput={scopeMode ? chatInput : reviewChatInput}
        setChatInput={scopeMode ? setChatInput : setReviewChatInput}
        openai={openai}
        onSend={scopeMode ? onSend : onSendReview}
        chatPending={scopeMode ? chatPending : reviewChatPending}
        scopeMode={scopeMode}
      />
    </section>
  );
}

function StepIndicator({
  phase,
  published,
  publishReady,
  onNavigatePhase,
  canNavigatePhase
}: {
  phase: DevPhase;
  published: boolean;
  publishReady?: boolean;
  onNavigatePhase?: (phase: DevPhase) => void;
  canNavigatePhase?: (phase: DevPhase) => boolean;
}) {
  const steps = [
    ["scope_chat", "Prompt"],
    ["building", "Build"],
    ["review", "Review"],
    ["published", "Publish"]
  ] as const;
  const activeIndex = published ? steps.length - 1 : steps.findIndex(([id]) => id === phase);
  return (
    <div className="step-indicator" data-testid="workflow-step-indicator">
      {steps.map(([id, label], index) => {
        const targetPhase = id === "published" ? "review" : id;
        const enabled = id === "published" ? published || Boolean(publishReady) : canNavigatePhase ? canNavigatePhase(targetPhase) : false;
        return (
          <button
            key={id}
            className={`stage-pill ${index < activeIndex ? "done" : index === activeIndex ? "active" : "pending"}`}
            type="button"
            disabled={!enabled}
            aria-label={`${label} step${id === "published" && publishReady && !published ? ", ready to publish" : ""}`}
            aria-current={index === activeIndex ? "step" : undefined}
            onClick={() => {
              if (!enabled || !onNavigatePhase) return;
              onNavigatePhase(targetPhase);
            }}
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}

function compactScopeSummary(value: string): string {
  const clean = sanitizeChatText(value || "No scope captured yet.");
  if (clean === "No scope captured yet.") return clean;
  return clean;
}

function splitScopeSummary(value: string): string[] {
  const summary = compactScopeSummary(value);
  if (summary === "No scope captured yet.") return [summary];
  return summary
    .replace(/\s+/g, " ")
    .split(/(?<=\.)\s+(?=(?:Key|Required|Revenue|The|There|Financing|Working|Tax|Cash|Debt|Equity|Model)\b)/)
    .map((part) => part.trim())
    .filter(Boolean);
}

const CORE_SCOPE_QUESTIONS = [
  "Business / asset",
  "Entities / assets",
  "Revenue and cost drivers",
  "Required outputs"
];

function normalizeScopeQuestion(value: string): string {
  const clean = sanitizeChatText(value).toLowerCase();
  if (/business|transaction|asset.*model|model.*asset/.test(clean)) return "Business / asset";
  if (/entities|entity|products|assets|facilities/.test(clean)) return "Entities / assets";
  if (/revenue|cost|drivers|price|volume/.test(clean)) return "Revenue and cost drivers";
  if (/outputs|statements|liquidity|valuation|debt|kpis|scenarios/.test(clean)) return "Required outputs";
  return sanitizeChatText(value);
}

function ModelSetupSummary({ decisions }: { decisions: string[] }) {
  const visible = decisions.filter(Boolean);
  if (!visible.length) return null;
  return (
    <article className="scope-summary-card">
      <h3>Captured notes</h3>
      <ul>
        {visible.slice(0, 5).map((item, index) => <li key={`${index}-${item.slice(0, 20)}`}>{item}</li>)}
      </ul>
    </article>
  );
}

function setupValue(items: string[], pattern: RegExp, fallback: string): string {
  const match = items.map((item) => sanitizeChatText(item)).find((item) => pattern.test(item));
  return match || fallback;
}

function horizonUnitLabel(periodicity: string): string {
  if (periodicity === "Monthly") return "months";
  if (periodicity === "Quarterly") return "quarters";
  return "years";
}

function defaultStartSubPeriod(periodicity: string): string {
  if (periodicity === "Monthly") return "01";
  if (periodicity === "Quarterly") return "Q1";
  return "";
}

function startSubPeriodOptions(periodicity: string): string[] {
  if (periodicity === "Monthly") return ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"];
  if (periodicity === "Quarterly") return ["Q1", "Q2", "Q3", "Q4"];
  return ["N/A"];
}

function startSubPeriodLabel(periodicity: string): string {
  if (periodicity === "Monthly") return "Start month";
  if (periodicity === "Quarterly") return "Start quarter";
  return "Start period";
}

function ModelSetupControls({ decisions, onChange }: { decisions: string[]; onChange: (values: ModelSetupState) => void }) {
  const joined = decisions.join(" ");
  const periodicity = /quarter/i.test(joined) ? "Quarterly" : /month/i.test(joined) ? "Monthly" : "Annual";
  const horizon = setupValue(decisions, /\d+\s*[- ]?year/i, "10-year horizon");
  const currency = /usd|\$/i.test(joined) ? "USD" : /gbp|£/i.test(joined) ? "GBP" : "EUR";
  const [values, setValues] = useState<ModelSetupState>({
    periodicity,
    startYear: "2026",
    startSubPeriod: defaultStartSubPeriod(periodicity),
    horizon: horizon.match(/\d+/)?.[0] || "10",
    currency,
    units: "Actuals"
  });
  useEffect(() => {
    onChange(values);
  }, [values, onChange]);
  function update(key: keyof typeof values, value: string) {
    setValues((current) => {
      if (key === "periodicity") {
        return { ...current, periodicity: value, startSubPeriod: defaultStartSubPeriod(value) };
      }
      if (key === "horizon") {
        return { ...current, horizon: value.replace(/\D/g, "") };
      }
      if (key === "startYear") {
        return { ...current, startYear: value.replace(/\D/g, "").slice(0, 4) };
      }
      return { ...current, [key]: value };
    });
  }
  const horizonUnit = horizonUnitLabel(values.periodicity);
  return (
    <article className="scope-summary-card compact model-setup-card" data-testid="model-setup-card">
      <h3>Model setup</h3>
      <div className="setup-control-grid">
        <label>
          Periodicity
          <select value={values.periodicity} onChange={(event) => update("periodicity", event.target.value)}>
            <option>Annual</option>
            <option>Quarterly</option>
            <option>Monthly</option>
          </select>
        </label>
        <label>
          Horizon
          <span className="number-with-suffix">
            <input
              type="text"
              inputMode="numeric"
              pattern="[0-9]*"
              value={values.horizon}
              aria-label={`Horizon in ${horizonUnit}`}
              onChange={(event) => update("horizon", event.target.value)}
            />
            <span>{horizonUnit}</span>
          </span>
        </label>
        <label>
          Start year
          <input
            type="text"
            inputMode="numeric"
            pattern="[0-9]{4}"
            maxLength={4}
            value={values.startYear}
            aria-label="Start year in yyyy"
            onChange={(event) => update("startYear", event.target.value)}
            data-testid="model-setup-start-year"
          />
        </label>
        <label className={values.periodicity === "Annual" ? "control-muted" : ""}>
          {startSubPeriodLabel(values.periodicity)}
          <select value={values.periodicity === "Annual" ? "N/A" : values.startSubPeriod} onChange={(event) => update("startSubPeriod", event.target.value)} disabled={values.periodicity === "Annual"} data-testid="model-setup-start-subperiod">
            {startSubPeriodOptions(values.periodicity).map((option) => <option key={option}>{option}</option>)}
          </select>
        </label>
        <label>
          Currency
          <select value={values.currency} onChange={(event) => update("currency", event.target.value)}>
            <option>EUR</option>
            <option>USD</option>
            <option>GBP</option>
          </select>
        </label>
        <label>
          Numbers formatting
          <select value={values.units} onChange={(event) => update("units", event.target.value)}>
            <option>Actuals</option>
            <option>Thousands</option>
            <option>Millions</option>
          </select>
        </label>
      </div>
    </article>
  );
}

void ModelSetupControls;

function ScopeWorkflowPanel({
  conversation,
  openai,
  packageState,
  chatInput,
  onGenerateModelSpec,
  onApproveModelSpec,
  onBuildModelPackage
}: {
  conversation: InputAgentConversation;
  openai: OpenAIState;
  packageState: PackageState;
  chatInput: string;
  onGenerateModelSpec: (prompt: string) => void;
  onApproveModelSpec: () => void;
  onBuildModelPackage: (prompt: string, openaiBacked?: boolean) => void;
}) {
  const lockedDecisions = conversation.locked_decisions || [];
  const spec = packageState.model_spec || {};
  const hasSpec = Boolean(packageState.model_spec && Object.keys(packageState.model_spec).length);
  const specApproved = packageState.model_spec_status === "approved";
  const specQuestions = Array.isArray(spec.unresolved_questions)
    ? spec.unresolved_questions.map((question) => String(question)).filter(Boolean)
    : [];
  const openQuestions = (specApproved ? specQuestions : conversation.open_questions || [])
    .map(cleanOpenQuestion)
    .filter((question) => stripModelSetupQuestions(question));
  const liveOpenAIUnavailable = openai.may_call_openai && !openai.api_key_configured;
  const modelPrompt = chatInput.trim() || conversation.scope_summary || "";
  const conversationSummary = conversation.scope_summary || "";
  const scopeSummary = conversationSummary && conversationSummary !== "No scope captured yet."
    ? conversationSummary
    : String(spec.scope_summary || spec.purpose || "No scope captured yet.");
  const canGenerateSpec = Boolean(modelPrompt.trim());
  const canApproveSpec = hasSpec && packageState.model_spec_status === "draft";
  const canBuildModel = specApproved;
  return (
    <section className="panel scope-workflow-panel" data-testid="scope-workflow-panel">
      {!openai.may_call_openai ? <UnitStubNotice /> : null}
      {liveOpenAIUnavailable ? (
        <div className="openai-notice warning" data-testid="openai-key-required-note">
          Add <code>OPENAI_API_KEY</code> to build a model.
        </div>
      ) : null}
      <aside className="scope-canvas" data-testid="scope-canvas">
        <div className="scope-canvas-header">
          <div>
            <h2>Build model</h2>
          </div>
          <div className="scope-action-row">
            {!hasSpec ? (
              <button
                className="primary-button"
                type="button"
                data-testid="model-spec-generate-button"
                onClick={() => onGenerateModelSpec(modelPrompt)}
                disabled={!canGenerateSpec || !openai.may_call_openai || !openai.api_key_configured}
                title={canGenerateSpec ? "Ask the Modeler Agent to draft model_spec.json." : "Enter a prompt in Chat first."}
              >
                Generate model spec
              </button>
            ) : null}
            {canApproveSpec ? (
              <button className="primary-button" type="button" data-testid="model-spec-approve-button" onClick={onApproveModelSpec}>
                Approve spec
              </button>
            ) : null}
            {hasSpec ? (
              <button
                className="secondary-button"
                type="button"
                data-testid="model-build-button"
                onClick={() => onBuildModelPackage(modelPrompt, true)}
                disabled={!canBuildModel || !openai.may_call_openai || !openai.api_key_configured}
                title={canBuildModel ? "Generate package files from the approved specification." : "Approve the model specification first."}
              >
                Build package
              </button>
            ) : null}
          </div>
        </div>
        <div className="scope-canvas-body">
          {hasSpec ? <ModelSpecCard packageState={packageState} /> : null}
          <article className="scope-summary-card">
            <h3>Summary</h3>
            <div className="scope-summary-text">
              {splitScopeSummary(scopeSummary).map((paragraph, index) => (
                <p key={`${index}-${paragraph.slice(0, 24)}`}>{paragraph}</p>
              ))}
            </div>
          </article>
          <ModelSetupSummary decisions={lockedDecisions} />
          <ScopeChecklist title={specApproved && !openQuestions.length ? "Specification complete" : "To be defined"} items={openQuestions} />
        </div>
      </aside>
    </section>
  );
}

function ModelSpecCard({ packageState }: { packageState: PackageState }) {
  const spec = packageState.model_spec || {};
  const readiness = spec.build_readiness && typeof spec.build_readiness === "object" ? spec.build_readiness as Record<string, unknown> : {};
  const blockers = Array.isArray(readiness.blockers) ? readiness.blockers.map((item) => String(item)).filter(Boolean) : [];
  const questions = Array.isArray(spec.unresolved_questions) ? spec.unresolved_questions.map((item) => String(item)).filter(Boolean) : [];
  const outputs = Array.isArray(spec.outputs) ? spec.outputs : [];
  const inputs = Array.isArray(spec.editable_inputs) ? spec.editable_inputs : [];
  const title = String(spec.title || "Model specification");
  const purpose = String(spec.purpose || spec.scope_summary || "");
  return (
    <article className="scope-summary-card" data-testid="model-spec-card">
      <div className="artifact-card-header">
        <div>
          <h3>{title}</h3>
          {purpose ? <p>{purpose}</p> : null}
        </div>
        <span className="badge subtle">{packageState.model_spec_status === "approved" ? "Approved" : "Draft"}</span>
      </div>
      <dl className="compact-definition-list">
        <dt>Editable inputs</dt>
        <dd>{inputs.length ? inputs.map((item) => specItemLabel(item)).join(", ") : "Not specified"}</dd>
        <dt>Outputs</dt>
        <dd>{outputs.length ? outputs.map((item) => specItemLabel(item)).join(", ") : "Not specified"}</dd>
      </dl>
      {blockers.length || questions.length ? (
        <div className="check-warning">
          {[...blockers, ...questions].map((item, index) => <p key={`${index}-${item}`}>{item}</p>)}
        </div>
      ) : null}
    </article>
  );
}

function specItemLabel(value: unknown): string {
  if (typeof value === "string") return value;
  if (value && typeof value === "object") {
    const row = value as Record<string, unknown>;
    return String(row.label || row.name || row.id || row.description || JSON.stringify(row));
  }
  return String(value ?? "");
}

function AgentChatPane({
  phase,
  conversation,
  chatInput,
  setChatInput,
  openai,
  onSend,
  chatPending,
  scopeMode
}: {
  phase: DevPhase;
  conversation: InputAgentConversation;
  chatInput: string;
  setChatInput: (value: string) => void;
  openai: OpenAIState;
  onSend: () => void;
  chatPending: boolean;
  scopeMode: boolean;
}) {
  const endRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" });
  }, [conversation.messages.length, chatPending]);
  const visibleMessages = conversation.messages.filter((message, index) => {
    if (!scopeMode) return true;
    if (index !== 0 || message.role !== "assistant") return true;
    return !message.content.startsWith("Tell me what model you want to build.") && !message.content.startsWith("Describe the model you want to build.");
  });
  const liveOpenAIUnavailable = openai.may_call_openai && !openai.api_key_configured;
  const canSend = Boolean(chatInput.trim()) && !chatPending && !liveOpenAIUnavailable;
  const openQuestions = scopeMode ? (conversation.open_questions || []).map(cleanOpenQuestion).filter((question) => stripModelSetupQuestions(question)) : [];
  const scopeNeedsAnswers = openQuestions.length > 0;
  const missingKeyReason = scopeMode ? "OPENAI_API_KEY is required for live scoping." : "OPENAI_API_KEY is required for live review chat answers.";
  const placeholder = scopeMode
    ? scopeNeedsAnswers
      ? "Answer the questions above"
      : conversation.ready_to_draft
        ? "Add any final scope details"
        : "Describe the model to start scoping"
    : `Ask about ${phaseLabel(phase).toLowerCase()}`;
  const chatHasVisibleContent = visibleMessages.length > 0 || chatPending;
  return (
    <aside className="panel development-agent-panel" data-testid="input-review-agent">
      <span className="sr-only" data-testid="active-agent">Chat</span>
      <div className="agent-panel-header">
        <div>
          <p className="eyebrow">{scopeMode ? "Model chat" : "Review chat"}</p>
          <h2>Chat</h2>
        </div>
        <span className="badge subtle">{phaseLabel(phase)}</span>
      </div>
      {liveOpenAIUnavailable ? (
        <div className="openai-notice warning" data-testid="review-openai-key-required-note">
          Add <code>OPENAI_API_KEY</code> to use live {scopeMode ? "scoping" : "review chat"}.
        </div>
      ) : null}
      <section className="scope-chat-pane" data-testid="input-agent-chat">
        <div className={`chat-thread ${chatHasVisibleContent ? "" : "empty"}`} data-testid="chat-log">
          {visibleMessages.map((message, index) => (
            <ChatBubble key={`${message.role}-${index}-${message.created_utc || ""}`} message={message} />
          ))}
          {chatPending ? <ThinkingIndicator /> : null}
          <div ref={endRef} />
        </div>
        <div className="chat-compose-row">
          <label className="chat-composer">
            <textarea
              data-testid="chat-input"
              value={chatInput}
              onChange={(event) => setChatInput(event.target.value)}
              placeholder={placeholder}
              rows={4}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.altKey && !event.shiftKey && !event.repeat) {
                  event.preventDefault();
                  const target = event.currentTarget;
                  const start = target.selectionStart;
                  const end = target.selectionEnd;
                  const nextValue = `${chatInput.slice(0, start)}\n${chatInput.slice(end)}`;
                  setChatInput(nextValue);
                  window.requestAnimationFrame(() => {
                    target.selectionStart = start + 1;
                    target.selectionEnd = start + 1;
                  });
                  return;
                }
                if (event.key === "Enter" && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey && !event.repeat) {
                  event.preventDefault();
                  if (canSend) void onSend();
                }
              }}
            />
            <button className="composer-send-button" type="button" data-testid="send-chat-button" onClick={onSend} disabled={!canSend} title={liveOpenAIUnavailable ? missingKeyReason : !chatInput.trim() ? "Enter a message first." : "Send"}>
              <svg className="send-arrow-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="m5 12 7-7 7 7" />
                <path d="M12 19V5" />
              </svg>
              <span className="sr-only">Send</span>
            </button>
          </label>
        </div>
      </section>
    </aside>
  );
}

function phaseLabel(phase: DevPhase): string {
  if (phase === "scope_chat") return "Scope";
  if (phase === "input_review") return "Inputs";
  if (phase === "building") return "Build";
  return "Build / Review";
}

function ScopeChecklist({ title, items }: { title: string; items: string[] }) {
  const normalizedOpen = new Set(items.map(normalizeScopeQuestion));
  const extraItems = items
    .map((item) => sanitizeChatText(item))
    .filter((item) => item && !CORE_SCOPE_QUESTIONS.includes(normalizeScopeQuestion(item)));
  return (
    <article className="scope-summary-card compact scope-checklist-card">
      <h3>{title}</h3>
      <ul className="scope-checklist" data-testid="scope-open-questions">
        {CORE_SCOPE_QUESTIONS.map((item) => {
          const open = normalizedOpen.has(item);
          return (
            <li key={item} className={open ? "open" : "complete"}>
              <span className="scope-check-box" aria-hidden="true">{open ? "" : "✓"}</span>
              <span>{item}</span>
            </li>
          );
        })}
        {extraItems.map((item, index) => (
          <li key={`${title}-extra-${index}`} className="open">
            <span className="scope-check-box" aria-hidden="true" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </article>
  );
}

function ChatBubble({ message }: { message: ChatMessage }) {
  const content = message.role === "assistant" ? stripModelSetupQuestions(message.content) : message.content.trim();
  if (!content) return null;
  return (
    <article className={`chat-bubble ${message.role}`} data-testid={`chat-message-${message.role}`}>
      {message.role === "user" ? <p>{content}</p> : <FormattedChatContent content={content} />}
    </article>
  );
}

function FormattedChatContent({ content }: { content: string }) {
  const lines = sanitizeChatText(content)
    .split(/\n+/)
    .map((line) => line.trim())
    .filter(Boolean);
  const blocks: Array<{ type: "list"; items: string[] } | { type: "paragraph"; text: string }> = [];
  let numberedItems: string[] = [];
  function flushList() {
    if (!numberedItems.length) return;
    blocks.push({ type: "list", items: numberedItems });
    numberedItems = [];
  }
  for (const line of lines) {
    const numbered = line.match(/^\d+[\.)]\s*(.+)$/);
    if (numbered) {
      numberedItems.push(numbered[1].trim());
      continue;
    }
    flushList();
    const inlineNumbered = line.match(/^\s*(?:\d+[\.)]\s+.+?)(?:\s+\d+[\.)]\s+.+)+$/);
    if (inlineNumbered) {
      const items = line
        .split(/\s+(?=\d+[\.)]\s+)/)
        .map((item) => item.replace(/^\d+[\.)]\s*/, "").trim())
        .filter(Boolean);
      if (items.length > 1) {
        blocks.push({ type: "list", items });
        continue;
      }
    }
    blocks.push({ type: "paragraph", text: line });
  }
  flushList();
  return (
    <>
      {blocks.map((block, index) => block.type === "list" ? (
        <ol className="chat-numbered-list" key={`list-${index}`}>
          {block.items.map((item, itemIndex) => <li key={`${itemIndex}-${item.slice(0, 20)}`}>{item}</li>)}
        </ol>
      ) : (
        <p key={`paragraph-${index}`}>{block.text}</p>
      ))}
    </>
  );
}

function ThinkingIndicator() {
  return (
    <article className="chat-bubble assistant pending" data-testid="chat-pending">
      <span className="thinking-spinner" aria-hidden="true" />
      <p>Input Agent is working</p>
    </article>
  );
}

function sanitizeChatText(value: string) {
  return value
    .replace(/\*\*/g, "")
    .replace(/[—–]/g, "-")
    .replace(/\s+\n/g, "\n")
    .trim();
}

const MODEL_SETUP_QUESTION_PATTERN = /\b(start\s+(year|month|quarter|period)|reporting\s+currency|currency|periodicity|granularity|forecast\s+granularity|model\s+setup|horizon)\b/i;

function stripModelSetupQuestions(value: string): string {
  const lines = sanitizeChatText(value).split(/\r?\n/);
  let removed = false;
  const kept = lines.filter((line) => {
    const clean = line.trim();
    const numbered = clean.match(/^\d+[\.)]\s*(.+)$/);
    const question = numbered?.[1] || clean;
    if (MODEL_SETUP_QUESTION_PATTERN.test(question) && (question.includes("?") || numbered || question.toLowerCase().startsWith("confirm "))) {
      removed = true;
      return false;
    }
    if (removed && /^(one|two|\d+)\s+(quick\s+)?(blocking\s+)?(input|inputs|question|questions)\s*:?\s*$/i.test(clean)) {
      return false;
    }
    return true;
  });
  let counter = 0;
  return kept
    .map((line) => {
      const match = line.match(/^(\s*)\d+[\.)]\s*(.+)$/);
      if (!match) return line;
      counter += 1;
      return `${match[1]}${counter}. ${match[2]}`;
    })
    .join("\n")
    .trim();
}

function cleanOpenQuestion(value: string): string {
  return sanitizeChatText(value)
    .replace(/,\s*horizon\b/gi, "")
    .replace(/\bhorizon,\s*/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
}

function InputReviewPanel({
  inputParams,
  inputReview,
  onInputChange
}: {
  inputParams: InputParams;
  inputReview: InputReviewSummary;
  onInputChange: (key: string, value: string) => void;
}) {
  return (
    <section className="review-stack input-review-workflow" data-testid="input-review-panel">
      <section className="panel">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Input review</p>
            <h2>Assumptions</h2>
          </div>
          <span className="control-reason">Review proposed assumptions here. Local rerun becomes available after publication.</span>
        </div>
        <InputsTable
          inputs={inputParams}
          inputReview={inputReview}
          onInputChange={onInputChange}
          openSections={{}}
        />
      </section>
    </section>
  );
}

function BuildProgressPanel({ steps, compact }: { steps: BuildStep[]; compact?: boolean }) {
  const visibleSteps = compact ? steps.filter((step) => step.state !== "pending" && step.state !== "skipped") : steps;
  if (compact && visibleSteps.length === 0) return null;
  return (
    <section className="panel build-progress" data-testid="build-progress">
      <p className="eyebrow">Build progress</p>
      <h2>{compact ? "Build sequence" : "Preparing the draft model"}</h2>
      <div className="build-step-list">
        {visibleSteps.map((step) => (
          <div key={step.id} className={`build-step ${step.state}`} data-testid={`build-step-${step.id}`}>
            <span>{buildStepStateLabel(step.state)}</span>
            <strong>{step.label}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function buildStepStateLabel(state: BuildStep["state"]): string {
  if (state === "complete") return "Done";
  if (state === "failed") return "Needs attention";
  if (state === "running") return "Running";
  if (state === "skipped") return "Not needed";
  return "Waiting";
}

function ReviewPanel({
  latestRun,
  model,
  packageState,
  inputParams,
  inputReview,
  buildSteps,
  openai,
  onPublish,
  onAmendPackage,
  onInputChange,
  amendmentPending
}: {
  latestRun: RunPayload | null;
  model: ModelManifest | null;
  packageState: PackageState;
  inputParams: InputParams;
  inputReview: InputReviewSummary;
  buildSteps: BuildStep[];
  openai: OpenAIState;
  onPublish: () => void;
  onAmendPackage: (message: string) => void;
  onInputChange: (key: string, value: string) => void;
  amendmentPending: boolean;
}) {
  void buildSteps;
  const packageStateResult = hasOutputBlocks(packageState.latest_output) ? (packageState.latest_output as ModelResult) : null;
  const result = packageStateResult || latestRun?.result || null;
  const validationSummary = (("passed" in packageState.validation_report ? packageState.validation_report : null) || latestRun?.validation_summary) as CheckSummary | null;
  const mechanicalSummary = ("passed" in (packageState.mechanical_stress_report || {}) ? packageState.mechanical_stress_report : null) as CheckSummary | null;
  const isPublishedCanonical = model?.status === "published" && (!packageState.version_id || packageState.version_id === packageState.canonical_version_id || packageState.status === "published");
  const showPublish = packageState.publish_eligible && !isPublishedCanonical;
  const isCustom = packageState.compiler_manifest?.support_tier === "review_required";
  const reviewHeadline = isCustom && packageState.status === "review_ready"
    ? "Technical checks passed; business review required"
    : packageState.status === "review_ready"
      ? "Review-ready"
      : packageState.status_label;
  if (packageState.status === "review_ready" || packageState.status === "review_failed") {
    return (
      <PrePublishWorkbench
        modelId={model?.model_id || ""}
        packageState={packageState}
        inputParams={inputParams}
        inputReview={inputReview}
        result={result}
        validationSummary={validationSummary}
        mechanicalSummary={mechanicalSummary}
        showPublish={showPublish}
        isCustom={isCustom}
        onPublish={onPublish}
        onAmendPackage={onAmendPackage}
        onInputChange={onInputChange}
        amendmentPending={amendmentPending}
      />
    );
  }
  return (
    <section className="review-stack" data-testid="review-screen">
      <section className="panel">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Review</p>
            <h2>{reviewHeadline}</h2>
          </div>
        </div>
        {!openai.may_call_openai ? <UnitStubNotice /> : null}
        <div className="button-row">
          {showPublish ? (
            <button className="primary-button" type="button" data-testid="publish-model-button" onClick={onPublish}>
              {isCustom ? "Publish reviewed custom model" : "Publish model"}
            </button>
          ) : null}
          {isPublishedCanonical ? <span className="badge pass" data-testid="published-canonical-note">Published canonical version</span> : null}
          {!packageState.publish_eligible && !isPublishedCanonical ? <span className="control-reason">Publishing appears after package checks pass on a draft version.</span> : null}
        </div>
      </section>
      <section className="panel review-checks-panel" data-testid="pre-publish-checks">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Pre-publish checks</p>
            <h2>Package checks</h2>
          </div>
          <span className="control-reason">Technical checks do not replace business review.</span>
        </div>
        <div className="review-metrics review-metrics-priority">
          <CheckSummaryPanel summary={validationSummary} emptyText="Run the package to populate validation." testId="validation-summary" />
        </div>
      </section>
      <section className="panel" data-testid="draft-inputs-panel">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Assumptions</p>
            <h2>Inputs</h2>
          </div>
          <span className="control-reason">Review proposed assumptions here. Local rerun becomes available after publication.</span>
        </div>
        <InputsTable inputs={inputParams} inputReview={inputReview} onInputChange={onInputChange} />
      </section>
      <ResultsSurface
        result={result}
        validationSummary={validationSummary}
        showReviewMetrics={false}
      />
    </section>
  );
}

function PrePublishWorkbench({
  modelId,
  packageState,
  inputParams,
  inputReview,
  result,
  validationSummary,
  mechanicalSummary,
  showPublish,
  isCustom,
  onPublish,
  onAmendPackage,
  onInputChange,
  amendmentPending
}: {
  modelId: string;
  packageState: PackageState;
  inputParams: InputParams;
  inputReview: InputReviewSummary;
  result: ModelResult | null;
  validationSummary: CheckSummary | null;
  mechanicalSummary: CheckSummary | null;
  showPublish: boolean;
  isCustom: boolean;
  onPublish: () => void;
  onAmendPackage: (message: string) => void;
  onInputChange: (key: string, value: string) => void;
  amendmentPending: boolean;
}) {
  const [amendmentText, setAmendmentText] = useState("");
  const [selectedArtifactPath, setSelectedArtifactPath] = useState("");
  const [selectedArtifact, setSelectedArtifact] = useState<PackageArtifact | null>(null);
  const [artifactError, setArtifactError] = useState("");
  const [artifactLoading, setArtifactLoading] = useState(false);
  const review = packageState.review_report || {};
  const presentation = packageState.presentation_agent_report || {};
  const repairPlan = packageState.repair_plan || {};
  const repairsUsed = Number(repairPlan.repairs_used || packageState.review_history?.repairs_used || 0);
  const maxRepairs = Number(repairPlan.max_repair_attempts || 3);
  const reviewRound = Number(repairPlan.review_round || 0);
  const reviewStatus = String(repairPlan.status || packageState.review_history?.status || packageState.status);
  const requiredAmendments = Array.isArray(review.required_amendments) ? review.required_amendments : [];
  const materialAmendments = requiredAmendments
    .filter((item) => item && typeof item === "object" && ["blocker", "high", "medium"].includes(String((item as Record<string, unknown>).severity || "")))
    .map((item) => {
      const amendment = item as Record<string, unknown>;
      return `${String(amendment.severity || "issue").toUpperCase()} · ${String(amendment.required_change || amendment.observed || amendment.issue_id || "Required amendment")}`;
    });
  const limitations = Array.isArray((packageState.model_thesis || {}).limitations)
    ? ((packageState.model_thesis || {}).limitations as Record<string, unknown>[]).map((item) => String(item.description || item.label || item.id || "Declared limitation"))
    : [];
  const failedReasons = packageState.review_failure_reasons || asStringList(review.failure_reasons);
  const humanQuestions = asStringList(review.human_questions);
  const findings = Array.isArray(review.findings) ? review.findings : [];
  const selfCheckCount = Number((packageState.modeler_self_check || {}).code_interpreter_call_count || 0);
  const reviewEvidenceCount = Number((packageState.review_execution_evidence || {}).code_interpreter_call_count || 0);
  const modelTests = Array.isArray(packageState.model_tests) ? packageState.model_tests : [];
  const toolCalls = Number((packageState.agent_tool_calls_report || {}).tool_call_count || 0);
  const prePublish = packageState.pre_publish_summary || {};
  const changeSummary = packageState.change_summary || {};
  function submitAmendment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const clean = amendmentText.trim();
    if (!clean || amendmentPending) return;
    onAmendPackage(clean);
    setAmendmentText("");
  }
  async function selectArtifact(path: string) {
    if (!modelId) return;
    setSelectedArtifactPath(path);
    setSelectedArtifact(null);
    setArtifactError("");
    setArtifactLoading(true);
    try {
      const payload = await readPackageArtifact(modelId, path);
      setSelectedArtifact(payload.artifact || null);
    } catch (error) {
      setArtifactError(error instanceof Error ? error.message : String(error));
    } finally {
      setArtifactLoading(false);
    }
  }
  return (
    <section className="review-stack pre-publish-workbench" data-testid="pre-publish-workbench">
      <section className="panel pre-publish-hero">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Pre-publish workbench</p>
            <h2>{packageState.status === "review_ready" ? "Technical checks passed; business review required" : "Package failed review"}</h2>
            <p className="control-reason">This is the package state that will be published if accepted.</p>
          </div>
          {showPublish ? (
            <button className="primary-button" type="button" data-testid="publish-model-button" onClick={onPublish}>
              {isCustom ? "Publish reviewed custom model" : "Publish model"}
            </button>
          ) : null}
        </div>
        {failedReasons.length ? <ReasonList title="Failure reasons" items={failedReasons} testId="pre-publish-failure-reasons" /> : null}
      </section>

      <section className="panel" data-testid="pre-publish-amendment">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Modeler amendment</p>
            <h2>Ask Modeler for changes</h2>
          </div>
          {Number(packageState.amendment_count || 0) > 0 ? <span className="badge">Version amendment {packageState.amendment_count}</span> : null}
        </div>
        <form className="chat-input-row amendment-input-row" onSubmit={submitAmendment}>
          <textarea
            data-testid="modeler-amendment-input"
            value={amendmentText}
            onChange={(event) => setAmendmentText(event.target.value)}
            placeholder="Request changes to inputs, model logic, scenarios, outputs, KPIs, or display choices."
            disabled={amendmentPending}
          />
          <button className="primary-button" type="submit" data-testid="modeler-amendment-submit" disabled={!amendmentText.trim() || amendmentPending}>
            {amendmentPending ? "Amending..." : "Send change"}
          </button>
        </form>
        <p className="control-reason">Each amendment creates a new draft version. The previous version stays in artifacts; the workspace shows the latest.</p>
        {Object.keys(changeSummary).length ? <ChangeSummary summary={changeSummary} /> : null}
      </section>

      <section className="pre-publish-grid">
        <article className="panel" data-testid="pre-publish-spec">
          <h3>Approved model spec</h3>
          <SpecPreview spec={packageState.model_spec || {}} />
        </article>
        <article className="panel" data-testid="pre-publish-review">
          <h3>Review Agent</h3>
          <p className="review-summary-text">{String(review.summary || "No Review Agent summary was recorded.")}</p>
          <dl className="compact-definition-list">
            <dt>Status</dt>
            <dd>{review.approved ? "Approved" : "Not approved"}</dd>
            <dt>Review round</dt>
            <dd>{reviewRound + 1}</dd>
            <dt>Modeler repairs</dt>
            <dd data-testid="review-repair-progress">{repairsUsed} of {maxRepairs}</dd>
            <dt>Iteration status</dt>
            <dd>{reviewStatus.replace(/_/g, " ")}</dd>
          </dl>
          {materialAmendments.length ? <ReasonList title="Unresolved material amendments" items={materialAmendments} testId="pre-publish-required-amendments" /> : null}
          {findings.length ? <FindingList findings={findings} /> : null}
          {limitations.length ? (
            <ReasonList title="Declared limitations" items={limitations} testId="pre-publish-limitations" />
          ) : (
            <p className="control-reason" data-testid="pre-publish-limitations">No package limitations were declared; business review should confirm whether that is credible.</p>
          )}
          {humanQuestions.length ? <ReasonList title="Human questions" items={humanQuestions} testId="pre-publish-human-questions" /> : null}
        </article>
      </section>

      <section className="panel" data-testid="pre-publish-inputs">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Regular Mode preview</p>
            <h2>Editable inputs</h2>
          </div>
          <span className="control-reason">These inputs become locally rerunnable after this package is reviewed and published.</span>
        </div>
        <InputsTable inputs={inputParams} inputReview={inputReview} onInputChange={onInputChange} />
      </section>

      <section className="panel review-checks-panel" data-testid="pre-publish-checks">
        <div className="panel-title-row">
          <div>
            <p className="eyebrow">Publish gates</p>
            <h2>Checks and stress</h2>
          </div>
          <span className="control-reason">Technical checks do not replace business review.</span>
        </div>
        <div className="review-metrics two-column-metrics">
          <CheckSummaryPanel summary={validationSummary} emptyText="Run the package to populate validation." testId="validation-summary" />
          <CheckSummaryPanel summary={mechanicalSummary} emptyText="Run the package to populate stress evidence." testId="mechanical-stress-summary" />
        </div>
      </section>

      <section className="panel" data-testid="pre-publish-technical-evidence">
        <h3>Technical evidence</h3>
        <dl className="compact-definition-list">
          <dt>Modeler self-check</dt>
          <dd>{selfCheckCount} python tool call{selfCheckCount === 1 ? "" : "s"}</dd>
          <dt>Presentation Agent</dt>
          <dd>{presentation.passed === true ? `Passed · ${friendlyLabel(String(presentation.template_id || "dashboard"))}` : String(presentation.status || "Not completed")}</dd>
          <dt>Review execution</dt>
          <dd>{reviewEvidenceCount} python tool call{reviewEvidenceCount === 1 ? "" : "s"}</dd>
          <dt>Model-local tests</dt>
          <dd>{modelTests.length} declared test{modelTests.length === 1 ? "" : "s"}</dd>
          <dt>Review function tools</dt>
          <dd>{toolCalls} backend tool call{toolCalls === 1 ? "" : "s"}</dd>
          <dt>Summary state</dt>
          <dd>{String(prePublish.status || packageState.status)}</dd>
        </dl>
      </section>

      <PackageArtifactBrowser
        artifacts={packageState.artifact_tree || []}
        selectedPath={selectedArtifactPath}
        selectedArtifact={selectedArtifact}
        loading={artifactLoading}
        error={artifactError}
        onSelect={selectArtifact}
      />

      <section data-testid="pre-publish-outputs">
        <ResultsSurface result={result} validationSummary={validationSummary} showReviewMetrics={false} />
      </section>
    </section>
  );
}

function SpecPreview({ spec }: { spec: Record<string, unknown> }) {
  const inputs = Array.isArray(spec.editable_inputs) ? spec.editable_inputs : [];
  const outputs = Array.isArray(spec.outputs) ? spec.outputs : [];
  const limitations = asStringList(spec.known_limitations);
  return (
    <div className="spec-preview">
      <h4>{String(spec.title || "Model specification")}</h4>
      <p>{String(spec.purpose || spec.scope_summary || "No purpose recorded.")}</p>
      <dl className="compact-definition-list">
        <dt>Inputs</dt>
        <dd>{inputs.length ? inputs.map((item) => specItemLabel(item)).join(", ") : "Not specified"}</dd>
        <dt>Outputs</dt>
        <dd>{outputs.length ? outputs.map((item) => specItemLabel(item)).join(", ") : "Not specified"}</dd>
      </dl>
      {limitations.length ? <ReasonList title="Known limitations" items={limitations} testId="pre-publish-limitations" /> : null}
    </div>
  );
}

function PackageArtifactBrowser({
  artifacts,
  selectedPath,
  selectedArtifact,
  loading,
  error,
  onSelect
}: {
  artifacts: PackageArtifact[];
  selectedPath: string;
  selectedArtifact: PackageArtifact | null;
  loading: boolean;
  error: string;
  onSelect: (path: string) => void;
}) {
  const files = artifacts
    .filter((artifact) => artifact.path && artifact.kind !== "directory")
    .sort((left, right) => left.path.localeCompare(right.path));
  const visible = files.filter((artifact) =>
    artifact.path.startsWith("model_package/model/") ||
    artifact.path.startsWith("model_package/spec/") ||
    artifact.path.startsWith("model_package/reports/") ||
    artifact.path.endsWith("model_thesis.json") ||
    artifact.path.endsWith("equation_graph.json") ||
    artifact.path.endsWith("model_tests.json")
  );
  const list = visible.length ? visible : files;
  return (
    <section className="panel" data-testid="pre-publish-artifact-browser">
      <div className="panel-title-row">
        <div>
          <p className="eyebrow">Package files</p>
          <h2>Artifact browser</h2>
        </div>
        <span className="control-reason">Inspect the exact files and reports behind this version.</span>
      </div>
      <div className="artifact-layout">
        <div className="artifact-list" role="list" aria-label="Package artifacts">
          {list.slice(0, 80).map((artifact) => (
            <button
              key={artifact.path}
              type="button"
              className={artifact.path === selectedPath ? "active" : ""}
              onClick={() => onSelect(artifact.path)}
            >
              {artifact.path}
            </button>
          ))}
          {!list.length ? <p className="control-reason">No package artifacts are available yet.</p> : null}
        </div>
        <div className="artifact-viewer" data-testid="pre-publish-artifact-viewer">
          {loading ? <p className="control-reason">Loading artifact...</p> : null}
          {error ? <p className="error-text">{error}</p> : null}
          {!loading && !error && selectedArtifact ? (
            <>
              <strong>{selectedArtifact.path}</strong>
              <pre>{formatArtifactContent(selectedArtifact.content)}</pre>
            </>
          ) : null}
          {!loading && !error && !selectedArtifact ? <p className="control-reason">Choose a package file or report to inspect it.</p> : null}
        </div>
      </div>
    </section>
  );
}

function formatArtifactContent(content: unknown): string {
  if (typeof content === "string") return content;
  if (content === null || content === undefined) return "";
  return JSON.stringify(content, null, 2);
}

function FindingList({ findings }: { findings: unknown[] }) {
  return (
    <ul className="finding-list" data-testid="pre-publish-review-findings">
      {findings.slice(0, 8).map((finding, index) => {
        const row = finding && typeof finding === "object" ? finding as Record<string, unknown> : { message: finding };
        return (
          <li key={`${index}-${String(row.message || row.area || "")}`}>
            <strong>{String(row.severity || row.area || "Finding")}</strong>
            <span>{String(row.message || row.summary || row.evidence || JSON.stringify(row))}</span>
          </li>
        );
      })}
    </ul>
  );
}

function ChangeSummary({ summary }: { summary: Record<string, unknown> }) {
  const hidden = new Set(["created_utc", "amendment_message"]);
  const rows = Object.entries(summary)
    .filter(([key, value]) => !hidden.has(key) && value !== null && value !== undefined && String(value).trim() !== "")
    .slice(0, 8);
  if (!rows.length) return null;
  return (
    <div className="reason-list" data-testid="pre-publish-change-summary">
      <strong>Latest change summary</strong>
      <ul>
        {rows.map(([key, value]) => (
          <li key={key}>
            <span>{friendlyLabel(key)}: {Array.isArray(value) ? value.map((item) => String(item)).join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ReasonList({ title, items, testId }: { title: string; items: string[]; testId: string }) {
  return (
    <div className="reason-list" data-testid={testId}>
      <strong>{title}</strong>
      <ul>
        {items.map((item) => <li key={item}>{item}</li>)}
      </ul>
    </div>
  );
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function hasOutputBlocks(value: unknown): boolean {
  return Boolean(value && typeof value === "object" && Array.isArray((value as { output_blocks?: unknown }).output_blocks));
}

export function RegularMode({
  selectedModel,
  inputs,
  inputReview,
  latestRun,
  packageState,
  activeTab,
  onInputChange,
  onRerun,
  inputErrors = {},
  showToolbar = true
}: {
  selectedModel?: ModelManifest | null;
  inputs: InputParams;
  inputReview: InputReviewSummary;
  latestRun: RunPayload | null;
  packageState: PackageState;
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  onInputChange: (key: string, value: string) => void;
  onRerun: () => void;
  onEnterDevelopment: () => void;
  inputErrors?: Record<string, string>;
  showToolbar?: boolean;
  inputDirty?: boolean;
  scenarioState?: "current" | "dirty" | "rerun_complete";
}) {
  const visibleTab = activeTab === "results" || activeTab === "model" || activeTab === "checks" ? activeTab : "inputs";
  const [openInputSections, setOpenInputSections] = useState<Record<string, boolean>>({ top_line: true, revenue: true, costs: true, liquidity: true, cash: true });
  const result = latestRun?.result || (hasOutputBlocks(packageState.latest_output) ? (packageState.latest_output as ModelResult) : null);
  const validationSummary = (latestRun?.validation_summary || ("passed" in packageState.validation_report ? packageState.validation_report : null)) as CheckSummary | null;
  return (
    <section className="regular-stack" data-testid="regular-mode">
      {showToolbar && visibleTab === "inputs" ? (
        <div className="regular-primary-action-row">
          <button className="primary-button" type="button" data-testid="rerun-inputs-button" onClick={onRerun} disabled={Object.keys(inputErrors).length > 0}>
            Rerun model
          </button>
        </div>
      ) : null}
      {visibleTab === "inputs" ? (
        <InputsTable
          inputs={inputs}
          inputReview={inputReview}
          onInputChange={onInputChange}
          inputErrors={inputErrors}
          openSections={openInputSections}
          onSectionToggle={(sectionId, open) => setOpenInputSections((current) => ({ ...current, [sectionId]: open }))}
        />
      ) : null}
      {visibleTab === "model" ? (
        <ModelArtifactSurface modelId={selectedModel?.model_id || ""} artifacts={packageState.artifact_tree || []} />
      ) : null}
      {visibleTab === "results" ? (
        <>
          <RegularModeTrustPanel selectedModel={selectedModel || null} packageState={packageState} latestRun={latestRun} />
          <ResultsSurface result={result} validationSummary={validationSummary} showReviewMetrics={false} />
        </>
      ) : null}
      {visibleTab === "checks" ? <ChecksSurface validationSummary={validationSummary} /> : null}
    </section>
  );
}

type ArtifactTreeNode = {
  name: string;
  path: string;
  artifact?: PackageArtifact;
  children: ArtifactTreeNode[];
};

function artifactTree(artifacts: PackageArtifact[]): ArtifactTreeNode[] {
  const root: ArtifactTreeNode = { name: "Package", path: "", children: [] };
  const visible = artifacts.filter((artifact) => {
    const path = String(artifact.path || "").replace(/\\/g, "/");
    return path.startsWith("model_package/model/") || path.startsWith("model_package/spec/") || path.startsWith("model_package/inputs/") || path.startsWith("model_package/outputs/") || path.startsWith("model_package/reports/");
  });
  for (const artifact of visible) {
    const parts = String(artifact.path).replace(/\\/g, "/").split("/").filter(Boolean);
    let parent = root;
    parts.forEach((name, index) => {
      const path = parts.slice(0, index + 1).join("/");
      let node = parent.children.find((child) => child.name === name);
      if (!node) {
        node = { name, path, children: [] };
        parent.children.push(node);
      }
      if (index === parts.length - 1 && artifact.kind !== "directory") node.artifact = artifact;
      parent = node;
    });
  }
  const sortNodes = (nodes: ArtifactTreeNode[]): ArtifactTreeNode[] => nodes.sort((a, b) => {
    const aFolder = a.children.length > 0 && !a.artifact;
    const bFolder = b.children.length > 0 && !b.artifact;
    if (aFolder !== bFolder) return aFolder ? -1 : 1;
    return a.name.localeCompare(b.name);
  }).map((node) => ({ ...node, children: sortNodes(node.children) }));
  return sortNodes(root.children);
}

function ModelArtifactSurface({ modelId, artifacts }: { modelId: string; artifacts: PackageArtifact[] }) {
  const [selectedPath, setSelectedPath] = useState("");
  const [selectedArtifact, setSelectedArtifact] = useState<PackageArtifact | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const tree = useMemo(() => artifactTree(artifacts), [artifacts]);
  async function selectFile(path: string) {
    if (!modelId) return;
    setSelectedPath(path);
    setSelectedArtifact(null);
    setError("");
    setLoading(true);
    try {
      const payload = await readPackageArtifact(modelId, path);
      setSelectedArtifact(payload.artifact || null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setLoading(false);
    }
  }
  function downloadSelected() {
    if (!selectedArtifact) return;
    const content = formatArtifactContent(selectedArtifact.content);
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = selectedArtifact.path.split("/").pop() || "artifact.txt";
    anchor.click();
    URL.revokeObjectURL(url);
  }
  async function copySelected() {
    if (!selectedArtifact || !navigator.clipboard) return;
    await navigator.clipboard.writeText(formatArtifactContent(selectedArtifact.content));
  }
  return (
    <section className="model-artifact-surface" data-testid="tab-model">
      <div className="model-artifact-header">
        <div><p className="eyebrow">Published Python package</p><h2>Model</h2><p>Inspect the exact source, assumptions, specification, outputs and review evidence behind this version.</p></div>
        <a className="secondary-button archive-download" href={packageArchiveUrl(modelId)} download data-testid="download-package-archive">Download package ZIP</a>
      </div>
      <div className="model-artifact-layout">
        <nav className="artifact-tree" aria-label="Model package files">
          <ArtifactTreeNodes nodes={tree} selectedPath={selectedPath} onSelect={selectFile} depth={0} />
          {!tree.length ? <p className="control-reason">No package artifacts are available.</p> : null}
        </nav>
        <article className="artifact-code-panel">
          {loading ? <p>Loading file…</p> : null}
          {error ? <p className="error-text">{error}</p> : null}
          {!loading && !error && selectedArtifact ? (
            <>
              <header><div><strong>{selectedArtifact.path}</strong><small>{selectedArtifact.size ? `${selectedArtifact.size.toLocaleString()} bytes` : "Generated artifact"}</small></div><div><button type="button" className="secondary-button" onClick={copySelected}>Copy</button><button type="button" className="secondary-button" onClick={downloadSelected}>Download file</button></div></header>
              <pre>{formatArtifactContent(selectedArtifact.content)}</pre>
            </>
          ) : null}
          {!loading && !error && !selectedArtifact ? <div className="artifact-empty-state"><span>⌘</span><h3>Select a model file</h3><p>Open a file from the package tree to inspect its exact contents.</p></div> : null}
        </article>
      </div>
    </section>
  );
}

function ArtifactTreeNodes({ nodes, selectedPath, onSelect, depth }: { nodes: ArtifactTreeNode[]; selectedPath: string; onSelect: (path: string) => void; depth: number }) {
  return (
    <ul className="artifact-tree-level" data-depth={depth}>
      {nodes.map((node) => {
        const folder = node.children.length > 0 && !node.artifact;
        return (
          <li key={node.path}>
            {folder ? (
              <details open={depth < 2}><summary><span className="tree-icon">▾</span><span>{node.name}</span></summary><ArtifactTreeNodes nodes={node.children} selectedPath={selectedPath} onSelect={onSelect} depth={depth + 1} /></details>
            ) : (
              <button type="button" className={selectedPath === node.path ? "active" : ""} onClick={() => onSelect(node.path)}><span className="tree-file-icon">{node.name.endsWith(".py") ? "PY" : node.name.endsWith(".json") ? "{}" : "·"}</span><span>{node.name}</span>{node.artifact?.size ? <small>{Math.max(1, Math.round(node.artifact.size / 1024))} KB</small> : null}</button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function RegularModeTrustPanel({
  selectedModel,
  packageState,
  latestRun
}: {
  selectedModel: ModelManifest | null;
  packageState: PackageState;
  latestRun: RunPayload | null;
}) {
  const evidence = latestRun?.rerun_execution_evidence || packageState.rerun_execution_evidence;
  const review = packageState.review_report || {};
  const reviewApproved = review.approved === true;
  const limitations = [
    ...asStringList((packageState.model_spec || {}).known_limitations),
    ...asStringList(review.known_limitations)
  ].filter((value, index, values) => values.indexOf(value) === index);
  const canonicalVersion = evidence?.canonical_version_id || packageState.canonical_version_id || selectedModel?.canonical_version_id;
  const currentVersion = packageState.version_id || selectedModel?.current_version_id;
  const callDelta = evidence?.openai_call_delta;
  const noOpenAI = evidence?.openai_called === false && callDelta === 0;
  const acceptancePassed = evidence?.passed === true;
  const rerunProof = !evidence
    ? "Not recorded yet — rerun an edited assumption to create evidence."
    : noOpenAI && acceptancePassed
      ? "Verified: saved package rerun completed with no OpenAI call."
      : noOpenAI
        ? "No OpenAI call recorded; rerun acceptance is incomplete."
        : "Not verified: rerun evidence recorded an OpenAI call or lacks a zero-call delta.";
  const rerunBadge = !evidence
    ? "Rerun proof pending"
    : noOpenAI && acceptancePassed
      ? "No-OpenAI rerun verified"
      : "Rerun proof not verified";
  return (
    <details className="regular-trust-strip" data-testid="regular-mode-trust-panel">
      <summary>
        <span className="trust-summary-main"><strong>Reviewed package</strong><span>{reviewApproved ? "Review Agent approved · business review required" : "Business review required"}</span></span>
        <span className={`badge ${noOpenAI && acceptancePassed ? "pass" : ""}`} data-testid="regular-rerun-proof">{rerunBadge}</span>
      </summary>
      <div className="regular-trust-details">
      <dl className="compact-definition-list" data-testid="regular-version-identity">
        <dt>Canonical version</dt>
        <dd>{canonicalVersion || "Not recorded"}</dd>
        <dt>Current package version</dt>
        <dd>{currentVersion || "Not recorded"}</dd>
        <dt>Review Agent</dt>
        <dd>{reviewApproved ? "Approved; business review still required" : "No approval recorded; business review required"}</dd>
        <dt>Saved entrypoint</dt>
        <dd>{evidence?.saved_entrypoint || packageState.package_entrypoint || "Not recorded"}</dd>
      </dl>
      <p className="control-reason" data-testid="regular-rerun-evidence-summary">{rerunProof}</p>
      {evidence ? (
        <dl className="compact-definition-list" data-testid="regular-rerun-evidence-details">
          <dt>Usage ledger before / after</dt>
          <dd>{evidence.usage_ledger_count_before ?? "?"} / {evidence.usage_ledger_count_after ?? "?"}</dd>
          <dt>OpenAI call delta</dt>
          <dd>{callDelta ?? "Not recorded"}</dd>
          <dt>Inputs changed</dt>
          <dd>{evidence.inputs_changed === true ? "Yes" : evidence.inputs_changed === false ? "No" : "Not recorded"}</dd>
          <dt>Outputs changed</dt>
          <dd>{evidence.output_changed === true ? "Yes" : evidence.output_changed === false ? "No" : "Not recorded"}</dd>
          <dt>Technical validation</dt>
          <dd>{evidence.validation_passed === true ? "Passed; business review required" : evidence.validation_passed === false ? "Failed" : "Not recorded"}</dd>
        </dl>
      ) : null}
      <div data-testid="regular-limitations">
        <h3>Known limitations</h3>
        {limitations.length ? (
          <ul className="finding-list">
            {limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
          </ul>
        ) : (
          <p className="control-reason">No known limitations were recorded. Business review is still required.</p>
        )}
      </div>
      </div>
    </details>
  );
}

function ChecksSurface({ validationSummary }: { validationSummary: CheckSummary | null }) {
  return (
    <section className="checks-surface" data-testid="tab-checks">
      <div className="review-metrics review-metrics-priority">
        <CheckSummaryPanel summary={validationSummary} emptyText="Run the package to populate validation." testId="validation-summary" />
      </div>
    </section>
  );
}

function ResultsSurface({
  result,
  validationSummary,
  showReviewMetrics = true,
}: {
  result: ModelResult | null;
  validationSummary: CheckSummary | null;
  showReviewMetrics?: boolean;
}) {
  const outputBlocks = Array.isArray(result?.output_blocks) ? result.output_blocks : [];
  if (outputBlocks.length) {
    return (
      <section className="results-surface" data-testid="tab-results">
        <OutputBlocksSurface blocks={outputBlocks} dashboardSpec={result?.dashboard_spec} />
        {showReviewMetrics ? (
          <div className="review-metrics">
            <CheckSummaryPanel summary={validationSummary} emptyText="Run the package to populate validation." testId="validation-summary" />
          </div>
        ) : null}
      </section>
    );
  }
  return (
    <section className="results-surface" data-testid="tab-results">
      <article className="panel inset-panel" data-testid="output-contract-problem">
        <h3>Output contract problem</h3>
        <p>The package did not return the required output_blocks contract.</p>
      </article>
      {showReviewMetrics ? (
        <div className="review-metrics">
          <CheckSummaryPanel summary={validationSummary} emptyText="Run the package to populate validation." testId="validation-summary" />
        </div>
      ) : null}
    </section>
  );
}

function isDashboardSpecV2(value: unknown): value is DashboardSpecV2 {
  if (!value || typeof value !== "object") return false;
  const spec = value as Record<string, unknown>;
  return spec.version === "2.0" && Array.isArray(spec.sections);
}

function OutputBlocksSurface({ blocks, dashboardSpec }: { blocks: OutputBlock[]; dashboardSpec?: Record<string, unknown> }) {
  if (isDashboardSpecV2(dashboardSpec)) return <FinanceDashboard blocks={blocks} spec={dashboardSpec} />;
  return (
    <section className="custom-results legacy-finance-dashboard" data-testid="output-blocks-surface">
      <header className="finance-dashboard-heading"><div><p className="eyebrow">Model output</p><h1>Financial dashboard</h1><p>Decision-useful outputs from the published model package.</p></div></header>
      <div className="kpi-grid" data-testid="output-kpi-blocks">
        {blocks.filter((block) => block.type === "kpi").map((block) => (
          <div className="kpi-card" key={block.id} data-testid={`output-block-${safeTestId(block.id)}`}>
            <span>{block.label}</span>
            <strong>{formatCell(block.data.value)}</strong>
            <small>{String(block.data.unit || " ")}</small>
          </div>
        ))}
      </div>
      <div className="finance-widget-grid" data-testid="output-renderable-blocks">
        {blocks.filter((block) => block.type !== "kpi").map((block) => <OutputBlockCard key={block.id} block={block} visual={block.type === "time_series" ? "line" : block.type === "scenario_comparison" ? "bar" : "table"} />)}
      </div>
    </section>
  );
}

function FinanceDashboard({ blocks, spec }: { blocks: OutputBlock[]; spec: DashboardSpecV2 }) {
  const byId = useMemo(() => new Map(blocks.map((block) => [block.id, block])), [blocks]);
  return (
    <section className="finance-dashboard" data-testid="output-blocks-surface" data-template={spec.template_id}>
      <header className="finance-dashboard-heading">
        <div><p className="eyebrow">{spec.currency} · {spec.display_units}</p><h1>{spec.title}</h1><p>{spec.subtitle}</p></div>
        <span className="dashboard-template-label">{friendlyLabel(spec.template_id)}</span>
      </header>
      <nav className="dashboard-section-nav" aria-label="Dashboard sections">
        {spec.sections.map((section) => <a key={section.id} href={`#dashboard-${safeTestId(section.id)}`}>{section.title}</a>)}
      </nav>
      {spec.sections.map((section) => (
        <section className="dashboard-section" id={`dashboard-${safeTestId(section.id)}`} key={section.id}>
          <div className="dashboard-section-title"><span /><h2>{section.title}</h2></div>
          <div className="finance-widget-grid">
            {section.widgets.map((widget) => {
              const block = byId.get(widget.block_id);
              if (!block) return null;
              return <OutputBlockCard key={widget.id} block={block} visual={widget.visual} widget={widget} />;
            })}
          </div>
        </section>
      ))}
    </section>
  );
}

function OutputBlockCard({ block, visual, widget }: { block: OutputBlock; visual?: string; widget?: DashboardWidget }) {
  const style = widget ? { gridColumn: `span ${Math.max(1, Math.min(12, widget.columns))}`, minHeight: `${Math.max(1, widget.rows) * 92}px` } : undefined;
  if (block.type === "kpi") {
    return <article className="finance-kpi-widget" style={style} data-testid={`output-block-${safeTestId(block.id)}`}><span>{block.label}</span><strong>{formatCell(block.data.value)}</strong><small>{String(block.data.unit || " ")}</small></article>;
  }
  if (visual && ["line", "bar", "combo", "heatmap", "tornado", "waterfall"].includes(visual)) {
    return <article className="finance-chart-widget" style={style} data-testid={`output-block-${safeTestId(block.id)}`}><header><h3>{block.label}</h3></header><FinanceChart block={block} visual={visual} options={widget?.options || {}} /></article>;
  }
  if (block.type === "table") {
    return <OutputTableBlock block={block} visual={visual} style={style} />;
  }
  if (block.type === "time_series") {
    return <article className="finance-chart-widget" style={style}><header><h3>{block.label}</h3></header><FinanceChart block={block} visual={visual || "line"} options={widget?.options || {}} /></article>;
  }
  if (block.type === "scenario_comparison") {
    return <article className="finance-chart-widget" style={style}><header><h3>{block.label}</h3></header><FinanceChart block={block} visual={visual || "bar"} options={widget?.options || {}} /></article>;
  }
  return (
    <article className="finance-text-widget" style={style} data-testid={`output-block-${safeTestId(block.id)}`}>
      <h3>{block.label}</h3>
      <StructuredDataPreview data={block.data} />
    </article>
  );
}

function OutputTableBlock({ block, visual, style }: { block: Extract<OutputBlock, { type: "table" }>; visual?: string; style?: React.CSSProperties }) {
  const columns = block.data.columns || [];
  const rows = block.data.rows || [];
  return (
    <article className={`finance-table-widget ${visual === "statement" ? "statement-widget" : ""}`} style={style} data-testid={`output-block-${safeTestId(block.id)}`}>
      <h3>{block.label}</h3>
      <div className="statement-scroll">
        <table>
          <thead>
            <tr>{columns.map((column) => <th key={column.id}>{column.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.slice(0, 50).map((row, index) => (
              <tr key={index}>
                {columns.map((column, columnIndex) => { const value = row[column.id]; const numeric = typeof value === "number"; return <td key={column.id} className={`${columnIndex === 0 ? "row-label" : ""} ${numeric && value < 0 ? "negative-value" : ""}`}>{formatCell(value)}</td>; })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function InputsTable({
  inputs,
  inputReview,
  onInputChange,
  readOnly,
  openSections,
  onSectionToggle,
  inputErrors = {}
}: {
  inputs: InputParams;
  inputReview: InputReviewSummary;
  onInputChange: (key: string, value: string) => void;
  readOnly?: boolean;
  openSections?: Record<string, boolean>;
  onSectionToggle?: (sectionId: string, open: boolean) => void;
  inputErrors?: Record<string, string>;
}) {
  if (isCustomModelInputs(inputs, inputReview)) {
    return (
      <CustomInputsTable
        inputs={inputs}
        inputReview={inputReview}
        onInputChange={onInputChange}
        readOnly={readOnly}
        openSections={openSections}
        onSectionToggle={onSectionToggle}
        inputErrors={inputErrors}
      />
    );
  }
  const rows = flattenInputRows(inputs);
  return (
    <section className="panel" data-testid="tab-inputs">
      <div className="panel-title-row">
        <h2>Inputs</h2>
        {readOnly ? <span className="badge subtle">Review copy</span> : null}
      </div>
      <div className="input-table-wrap">
        <table className="inputs-table" data-testid="inputs-grid">
          <tbody>
            {rows.map(({ path, value }) => {
              const label = fallbackInputLabel(path);
              const inferredField: InputReviewItem | undefined = path.startsWith("implied.")
                ? { key: path, path, label, read_only: true, editable: false, input_role: "implied", provenance: "implied" }
                : undefined;
              const locked = fieldIsReadOnly(inferredField, readOnly);
              return (
                <tr key={path}>
                  <th>{label}</th>
                  <td>
                    {locked ? (
                      inputValue(value, inferredField)
                    ) : (
                      <input data-testid={`input-${safeTestId(path)}`} value={inputValue(value, inferredField)} onChange={(event) => onInputChange(path, event.target.value)} />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <InputReview summary={inputReview} />
    </section>
  );
}

function flattenInputRows(inputs: InputParams): { path: string; value: unknown }[] {
  const rows: { path: string; value: unknown }[] = [];
  const visit = (prefix: string, value: unknown) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      Object.entries(value as Record<string, unknown>).forEach(([key, child]) => visit(prefix ? `${prefix}.${key}` : key, child));
      return;
    }
    if (prefix) rows.push({ path: prefix, value });
  };
  Object.entries(inputs).forEach(([key, value]) => visit(key, value));
  return rows;
}

function fallbackInputLabel(path: string): string {
  const parts = path.split(".").filter(Boolean);
  const leaf = path.includes(".") ? parts[parts.length - 1] || path : path;
  return inputLabel(leaf);
}

function safeTestId(path: string) {
  return path.replace(/[^a-zA-Z0-9_-]/g, "-");
}

function fieldProvenance(field?: InputReviewItem): string {
  const value = String(field?.provenance || "placeholder");
  if (/implied/i.test(value) || field?.read_only || field?.editable === false) return "implied";
  if (/user|provided|required/i.test(value)) return "provided";
  if (/default/i.test(value)) return "defaulted";
  if (/missing|unknown/i.test(value)) return "missing";
  if (/placeholder/i.test(value)) return "placeholder";
  return "review";
}

function provenanceText(field?: InputReviewItem): string {
  if (field?.reason) return String(field.reason);
  if (field?.formula) return "Implied from other declared inputs.";
  return String(field?.provenance || "Generated assumption should be reviewed.");
}

function fieldIsReadOnly(field?: InputReviewItem, readOnly?: boolean): boolean {
  return Boolean(readOnly || field?.read_only || field?.editable === false || fieldProvenance(field) === "implied");
}

function inputSchemaFields(inputReview: InputReviewSummary): InputReviewItem[] {
  const schemaFields = inputReview.input_schema?.fields || [];
  const reviewFields = inputReview.canonical_inputs || [];
  const source = schemaFields.length ? schemaFields : reviewFields;
  return source.filter((field) => field.path || field.key);
}

function inputSourceLabel(field?: InputReviewItem): string {
  const source = fieldProvenance(field);
  if (source === "provided") return "Provided";
  if (source === "defaulted") return "Default";
  if (source === "missing") return "Missing";
  if (source === "implied") return "Implied";
  if (source === "placeholder") return "Placeholder";
  return "Review";
}

function inputUnitLabel(field?: InputReviewItem, path = ""): string {
  const rawUnit = String(field?.unit || field?.display_scale || "").trim();
  if (!rawUnit) return "-";
  const context = `${path} ${field?.key || ""} ${field?.label || ""} ${field?.group || ""}`.toLowerCase();
  if (field?.display_scale === "percent" || rawUnit === "percent") return "%";
  if (/^days?$/.test(rawUnit.toLowerCase()) || /\b(dso|dio|dpo|days? per year|days?_per_year|receivable days?|inventory days?|payable days?)\b/.test(context)) return "Days";
  return friendlyLabel(rawUnit);
}

function inputFinanceCategory(field: InputReviewItem, path: string): string {
  const text = `${field.group || ""} ${field.label || ""} ${path}`.toLowerCase();
  if (/equity|retained/.test(text)) return "Equity";
  if (/debt|loan|interest|repayment|financing/.test(text)) return "Debt";
  if (/dso|dpo|receivable|payable|working.?capital|nwc|inventory|days per year|days_per_year/.test(text)) return "Working capital";
  if (/cash/.test(text)) return "Cash";
  if (/ppe|pp&e|capex|depreciation|asset/.test(text)) return "Assets";
  if (/tax/.test(text)) return "Tax";
  if (/cogs|sg&a|sga|opex|cost|expense/.test(text)) return "Costs";
  if (/revenue|growth|price|volume|sales|margin/.test(text)) return "Revenue";
  if (/horizon|year|period|timeline|start/.test(text)) return "Timeline";
  return "Other";
}

const INPUT_CATEGORY_ORDER = ["Revenue", "Costs", "Working capital", "Cash", "Assets", "Debt", "Equity", "Tax", "Timeline", "Other"];

function CustomInputsTable({
  inputs,
  inputReview,
  onInputChange,
  readOnly,
  openSections,
  onSectionToggle,
  inputErrors = {}
}: {
  inputs: InputParams;
  inputReview: InputReviewSummary;
  onInputChange: (key: string, value: string) => void;
  readOnly?: boolean;
  openSections?: Record<string, boolean>;
  onSectionToggle?: (sectionId: string, open: boolean) => void;
  inputErrors?: Record<string, string>;
}) {
  const customInputView = useMemo(() => {
    const fields = inputSchemaFields(inputReview);
    const fieldsByPath = new Map(fields.map((field) => [String(field.path || field.key), field]));
    const equipment = inputs.equipment && typeof inputs.equipment === "object" && !Array.isArray(inputs.equipment) ? inputs.equipment as Record<string, unknown> : {};
    const arraySections = Object.entries(inputs).filter(([, value]) => Array.isArray(value) && (value as unknown[]).some((item) => item && typeof item === "object" && !Array.isArray(item))) as [string, Record<string, unknown>[]][];
    const usedPaths = new Set<string>();
    Object.entries(equipment)
      .filter(([, value]) => value && typeof value === "object" && !Array.isArray(value))
      .forEach(([key, value]) => Object.keys(value as Record<string, unknown>).forEach((column) => usedPaths.add(`equipment.${key}.${column}`)));
    arraySections.forEach(([key, value]) => {
      value.forEach((row, index) => Object.keys(row).forEach((column) => usedPaths.add(`${key}.${index}.${column}`)));
    });
    const groupedFields = new Map<string, InputReviewItem[]>();
    fields
      .filter((field) => !usedPaths.has(String(field.path || field.key)))
      .forEach((field) => {
        const path = String(field.path || field.key);
        const category = inputFinanceCategory(field, path);
        groupedFields.set(category, [...(groupedFields.get(category) || []), field]);
      });
    const financeGroups = Array.from(groupedFields.entries())
      .map(([label, groupFields]) => ({ id: safeTestId(label), label, fields: groupFields }))
      .sort((a, b) => INPUT_CATEGORY_ORDER.indexOf(a.label) - INPUT_CATEGORY_ORDER.indexOf(b.label));
    return { groups: financeGroups, fieldsByPath, equipment, arraySections, usedPaths };
  }, [inputs, inputReview]);
  const { groups, fieldsByPath, equipment, arraySections } = customInputView;
  const unresolvedReviewItems = [...(inputReview.missing_inputs || []), ...(inputReview.ambiguous_inputs || [])];
  return (
    <section className="custom-inputs" data-testid="tab-inputs">
      {Object.keys(equipment).length ? (
        <NestedObjectRows
          title="Equipment categories"
          basePath="equipment"
          rows={equipment}
          fieldsByPath={fieldsByPath}
          onInputChange={onInputChange}
          readOnly={readOnly}
        />
      ) : null}
      {arraySections.map(([key, value]) => (
        <ArrayObjectRows key={key} title={friendlyLabel(key)} basePath={key} rows={value} fieldsByPath={fieldsByPath} onInputChange={onInputChange} readOnly={readOnly} />
      ))}
      {groups.map((group) => {
        return (
          <details
            className="finance-input-section"
            key={group.id}
            data-testid={`input-group-${group.id}`}
            open={Boolean(openSections?.[group.id])}
            onToggle={(event) => onSectionToggle?.(group.id, event.currentTarget.open)}
          >
            <summary>{group.label}</summary>
            <table className="inputs-table finance-input-table">
              <colgroup>
                <col className="input-name-col" />
                <col className="input-unit-col" />
                <col className="input-value-col" />
                <col className="input-source-col" />
              </colgroup>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Unit</th>
                  <th>Value</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {group.fields.map((field) => {
                  const path = String(field.path || field.key);
                  const value = getByPath(inputs, path);
                  return <InputFieldRow key={path} path={path} value={value} field={field} readOnly={readOnly} onInputChange={onInputChange} error={inputErrors[path]} />;
                })}
              </tbody>
            </table>
          </details>
        );
      })}
      {unresolvedReviewItems.length ? (
        <div className="input-review-grid" data-testid="input-review">
          <InputReviewCard title="Needs review" items={unresolvedReviewItems} emptyLabel="No unresolved inputs." />
        </div>
      ) : null}
    </section>
  );
}

function NestedObjectRows({
  title,
  basePath,
  rows,
  fieldsByPath,
  onInputChange,
  readOnly
}: {
  title: string;
  basePath: string;
  rows: Record<string, unknown>;
  fieldsByPath: Map<string, InputReviewItem>;
  onInputChange: (key: string, value: string) => void;
  readOnly?: boolean;
}) {
  const entries = Object.entries(rows).filter(([, value]) => value && typeof value === "object" && !Array.isArray(value)) as [string, Record<string, unknown>][];
  if (!entries.length) return null;
  const columns = Array.from(new Set(entries.flatMap(([, row]) => Object.keys(row))));
  return (
    <section className="input-group" data-testid={`input-group-${basePath}`}>
      <h3>{title}</h3>
      <div className="statement-scroll">
        <table className="inputs-table nested-input-table" data-testid={`${basePath}-input-table`}>
          <thead>
            <tr>
              <th>Category</th>
              {columns.map((column) => <th key={column}>{friendlyLabel(column)}</th>)}
            </tr>
          </thead>
          <tbody>
            {entries.map(([key, row]) => (
              <tr key={key}>
                <th>{friendlyLabel(key)}</th>
                {columns.map((column) => {
                  const path = `${basePath}.${key}.${column}`;
                  const field = fieldsByPath.get(path);
                  return (
                    <td key={path}>
                      {fieldIsReadOnly(field, readOnly) ? inputValue(row[column], field) : <input title={provenanceText(field)} data-testid={`input-${safeTestId(path)}`} value={inputValue(row[column], field)} onChange={(event) => onInputChange(path, event.target.value)} />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ArrayObjectRows({
  title,
  basePath,
  rows,
  fieldsByPath,
  onInputChange,
  readOnly
}: {
  title: string;
  basePath: string;
  rows: Record<string, unknown>[];
  fieldsByPath: Map<string, InputReviewItem>;
  onInputChange: (key: string, value: string) => void;
  readOnly?: boolean;
}) {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return (
    <section className="input-group" data-testid={`input-group-${basePath}`}>
      <h3>{title}</h3>
      <div className="statement-scroll">
        <table className="inputs-table nested-input-table">
          <thead>
            <tr>{columns.map((column) => <th key={column}>{friendlyLabel(column)}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index}>
                {columns.map((column) => {
                  const path = `${basePath}.${index}.${column}`;
                  const field = fieldsByPath.get(path);
                  return (
                    <td key={path}>
                      {fieldIsReadOnly(field, readOnly) ? inputValue(row[column], field) : <input title={provenanceText(field)} data-testid={`input-${safeTestId(path)}`} value={inputValue(row[column], field)} onChange={(event) => onInputChange(path, event.target.value)} />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function InputFieldRow({ path, value, field, readOnly, onInputChange, error }: { path: string; value: unknown; field?: InputReviewItem; readOnly?: boolean; onInputChange: (key: string, value: string) => void; error?: string }) {
  const locked = fieldIsReadOnly(field, readOnly);
  const scheduled = field?.type === "number_or_13_number_array" || field?.type === "number_or_number_array";
  if (scheduled && !locked && field) {
    return (
      <tr className={`weekly-input-row ${error ? "input-row-error" : ""}`}>
        <th>{field.label || inputLabel(path)}</th>
        <td><span className="unit-label">{inputUnitLabel(field, path)}</span></td>
        <td colSpan={2}>
          <FlexibleScheduleEditor path={path} value={value} field={field} onInputChange={onInputChange} error={error} />
          <span className={`source-label ${fieldProvenance(field)}`} title={provenanceText(field)}>{inputSourceLabel(field)}</span>
        </td>
      </tr>
    );
  }
  return (
    <tr className={error ? "input-row-error" : ""}>
      <th>{field?.label || inputLabel(path)}</th>
      <td>
        <span className="unit-label">{inputUnitLabel(field, path)}</span>
      </td>
      <td>
        {locked ? (
          <strong>{inputValue(value, field)}</strong>
        ) : (
          <>
            <input data-testid={`input-${safeTestId(path)}`} value={inputValue(value, field)} title={provenanceText(field)} aria-invalid={Boolean(error)} onChange={(event) => onInputChange(path, event.target.value)} />
            {error ? <span className="input-error" role="alert">{error}</span> : null}
          </>
        )}
      </td>
      <td title={provenanceText(field)}>
        <span className={`source-label ${fieldProvenance(field)}`}>{inputSourceLabel(field)}</span>
      </td>
    </tr>
  );
}

function StructuredDataPreview({ data }: { data: Record<string, unknown> }) {
  const text = typeof data.text === "string" ? data.text : typeof data.summary === "string" ? data.summary : "";
  if (text) return <p>{text}</p>;
  return <dl className="structured-data-list">{Object.entries(data).slice(0, 20).map(([key, value]) => <div key={key}><dt>{friendlyLabel(key)}</dt><dd>{Array.isArray(value) ? `${value.length} items` : value && typeof value === "object" ? "Structured detail" : formatCell(value)}</dd></div>)}</dl>;
}

function FinanceChart({ block, visual, options }: { block: OutputBlock; visual: string; options: Record<string, unknown> }) {
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = echarts.init(containerRef.current, undefined, { renderer: "svg" });
    chart.setOption(financeChartOption(block, visual, options), { notMerge: true });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    observer?.observe(containerRef.current);
    return () => { observer?.disconnect(); window.removeEventListener("resize", resize); chart.dispose(); };
  }, [block, visual, options]);
  return <div className="echarts-finance-chart" ref={containerRef} role="img" aria-label={block.label} />;
}

function financeChartOption(block: OutputBlock, visual: string, options: Record<string, unknown>): echarts.EChartsOption {
  const palette = ["#0b3b60", "#14a6a1", "#e1a83b", "#6b7f93", "#d96b6b", "#8b6db1"];
  const common: echarts.EChartsOption = { animationDuration: 450, color: palette, textStyle: { fontFamily: "Inter, Segoe UI, sans-serif", color: "#334155" }, tooltip: { trigger: "axis", valueFormatter: (value: unknown) => typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value) }, grid: { left: 60, right: 24, top: 42, bottom: 44, containLabel: true } };
  if (visual === "heatmap" && block.type === "table") {
    const rows = block.data.rows || [];
    const rowField = String(options.row_field || "row"); const columnField = String(options.column_field || "column"); const valueField = String(options.value_field || "value");
    const y = Array.from(new Set(rows.map((row) => String(row[rowField])))); const x = Array.from(new Set(rows.map((row) => String(row[columnField]))));
    const data = rows.map((row) => [x.indexOf(String(row[columnField])), y.indexOf(String(row[rowField])), Number(row[valueField])]);
    const values = data.map((item) => Number(item[2])).filter(Number.isFinite);
    return { ...common, tooltip: { position: "top" }, xAxis: { type: "category", data: x, splitArea: { show: true } }, yAxis: { type: "category", data: y, splitArea: { show: true } }, visualMap: { min: Math.min(...values), max: Math.max(...values), calculable: true, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#e8f4f3", "#65c7c1", "#0b3b60"] } }, series: [{ type: "heatmap", data, label: { show: true, formatter: (params: any) => Number(params.value[2]).toLocaleString(undefined, { maximumFractionDigits: 1 }) } }] };
  }
  if (visual === "tornado" && block.type === "table") {
    const rows = block.data.rows || []; const driver = String(options.driver_field || "driver"); const low = String(options.downside_field || "downside"); const base = String(options.base_field || "base"); const high = String(options.upside_field || "upside");
    return { ...common, legend: { top: 4 }, xAxis: { type: "value", axisLabel: { formatter: (value: number) => value.toLocaleString() } }, yAxis: { type: "category", data: rows.map((row) => String(row[driver])), axisLabel: { width: 130, overflow: "truncate" } }, series: [{ name: "Downside", type: "bar", data: rows.map((row) => Number(row[low]) - Number(row[base])), itemStyle: { color: "#d96b6b" } }, { name: "Upside", type: "bar", data: rows.map((row) => Number(row[high]) - Number(row[base])), itemStyle: { color: "#14a6a1" } }] };
  }
  if (visual === "waterfall" && block.type === "table") {
    const rows = block.data.rows || []; const columns = block.data.columns || [];
    const labelField = String(options.label_field || columns[0]?.id || "label"); const valueField = String(options.value_field || columns[1]?.id || "value");
    const values = rows.map((row) => Number(row[valueField]) || 0); let running = 0;
    const offsets = values.map((value) => { const start = value >= 0 ? running : running + value; running += value; return start; });
    return { ...common, tooltip: { trigger: "axis", axisPointer: { type: "shadow" } }, xAxis: { type: "category", data: rows.map((row) => String(row[labelField])) }, yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf2f7" } } }, series: [{ type: "bar", stack: "waterfall", data: offsets, itemStyle: { color: "transparent", borderColor: "transparent" }, emphasis: { disabled: true }, tooltip: { show: false } }, { name: friendlyLabel(valueField), type: "bar", stack: "waterfall", data: values.map((value) => ({ value: Math.abs(value), itemStyle: { color: value >= 0 ? "#14a6a1" : "#d96b6b" } })), label: { show: true, position: "top", formatter: (params: any) => values[params.dataIndex].toLocaleString(undefined, { maximumFractionDigits: 1 }) } }] };
  }
  if (block.type === "time_series") {
    const visualMap = options.series_visuals && typeof options.series_visuals === "object" ? options.series_visuals as Record<string, unknown> : {};
    return { ...common, legend: { top: 4 }, xAxis: { type: "category", data: block.data.x, axisLine: { lineStyle: { color: "#cbd5e1" } } }, yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf2f7" } } }, series: block.data.series.map((series, index) => ({ name: series.label, type: visual === "combo" ? (visualMap[series.id] === "line" ? "line" : "bar") : visual === "bar" ? "bar" : "line", data: series.values, smooth: visual !== "bar", symbolSize: 7, lineStyle: { width: 2.5 }, areaStyle: visual === "line" && index === 0 ? { opacity: 0.05 } : undefined })) };
  }
  if (block.type === "scenario_comparison") {
    return { ...common, legend: { top: 4 }, xAxis: { type: "category", data: block.data.scenarios.map((scenario) => scenario.label) }, yAxis: { type: "value", splitLine: { lineStyle: { color: "#edf2f7" } } }, series: block.data.metrics.map((metric) => ({ name: metric.label, type: "bar", data: block.data.scenarios.map((scenario) => Number(metric.values[scenario.id])) })) };
  }
  if (block.type === "table") {
    const columns = block.data.columns; const category = String(options.category_field || columns[0]?.id || "label"); const valueFields = (Array.isArray(options.value_fields) ? options.value_fields : columns.slice(1).map((column) => column.id)).map(String);
    return { ...common, legend: { top: 4 }, xAxis: { type: "category", data: block.data.rows.map((row) => String(row[category])) }, yAxis: { type: "value" }, series: valueFields.map((field) => ({ name: friendlyLabel(field), type: visual === "line" ? "line" : "bar", data: block.data.rows.map((row) => Number(row[field])) })) };
  }
  return common;
}

function FlexibleScheduleEditor({ path, value, field, onInputChange, error }: { path: string; value: unknown; field: InputReviewItem; onInputChange: (key: string, value: string) => void; error?: string }) {
  const [setAllValue, setSetAllValue] = useState("");
  const testId = safeTestId(path);
  const periodCount = field.type === "number_or_13_number_array" ? 13 : Number(field.period_count || 0);
  const periodLabels = field.type === "number_or_13_number_array"
    ? Array.from({ length: 13 }, (_, index) => `Week ${index + 1}`)
    : Array.isArray(field.period_labels) && field.period_labels.length === periodCount
      ? field.period_labels
      : Array.from({ length: periodCount }, (_, index) => `Period ${index + 1}`);
  const cadenceLabel = field.type === "number_or_13_number_array" ? "week" : "period";
  if (!Array.isArray(value)) {
    const display = inputValue(value, field);
    return (
      <div className="weekly-schedule-editor" data-testid={`weekly-editor-${testId}`}>
        <input data-testid={`input-${testId}`} value={display} title={provenanceText(field)} aria-invalid={Boolean(error)} onChange={(event) => onInputChange(path, event.target.value)} />
        <button className="secondary-button compact-button" type="button" data-testid={`expand-weekly-${testId}`} onClick={() => onInputChange(path, Array(periodCount).fill(display).join(","))}>Edit by {cadenceLabel}</button>
        {error ? <span className="input-error" role="alert">{error}</span> : null}
      </div>
    );
  }
  const displayValues = value.map((item) => inputValue(item, field));
  const updateWeek = (index: number, raw: string) => {
    const next = [...displayValues];
    next[index] = raw;
    onInputChange(path, next.join(","));
  };
  return (
    <div className="weekly-schedule-editor expanded" data-testid={`weekly-editor-${testId}`}>
      <div className="weekly-set-all">
        <input aria-label={`Set all periods for ${field.label || path}`} value={setAllValue} onChange={(event) => setSetAllValue(event.target.value)} placeholder="Set all periods" />
        <button className="secondary-button compact-button" type="button" onClick={() => onInputChange(path, Array(periodCount).fill(setAllValue).join(","))}>Apply</button>
      </div>
      <div className="weekly-value-grid">
        {displayValues.map((display, index) => (
          <label key={`${path}-${index}`}>
            <span>{periodLabels[index]}</span>
            <input data-testid={`input-${testId}-week-${index + 1}`} value={display} aria-invalid={Boolean(error)} onChange={(event) => updateWeek(index, event.target.value)} />
          </label>
        ))}
      </div>
      {error ? <span className="input-error" role="alert">{error}</span> : null}
    </div>
  );
}

export function HeaderBar({
  phase,
  published,
  publishReady,
  modelName,
  statusLabel,
  activeTab,
  setActiveTab,
  inputDirty,
  onRerun,
  onEnterDevelopment,
  onNavigatePhase,
  canNavigatePhase
}: {
  theme?: string;
  setTheme?: (theme: string) => void;
  compact?: boolean;
  onHome?: () => void;
  phase?: DevPhase;
  published?: boolean;
  publishReady?: boolean;
  modelName?: string;
  statusLabel?: string;
  activeTab?: ActiveTab;
  setActiveTab?: (tab: ActiveTab) => void;
  inputDirty?: boolean;
  onRerun?: () => void;
  onEnterDevelopment?: () => void;
  onNavigatePhase?: (phase: DevPhase) => void;
  canNavigatePhase?: (phase: DevPhase) => boolean;
}) {
  if (!modelName) return null;
  return (
    <header className="model-context-bar" data-testid="model-context-bar">
      <div className="model-context-left">
        <span className="header-model-name">{modelName}</span>
        <span className={`badge ${statusLabel?.toLowerCase().includes("draft") ? "draft" : "active-state"}`} data-testid="selected-model-status">
          {statusLabel || "Draft"}
        </span>
      </div>
      {published ? (
        <PublishedModelToolbar
          activeTab={activeTab === "results" || activeTab === "model" || activeTab === "checks" ? activeTab : "inputs"}
          setActiveTab={setActiveTab}
          inputDirty={Boolean(inputDirty)}
          onRerun={onRerun}
          onEnterDevelopment={onEnterDevelopment}
        />
      ) : phase ? (
        <StepIndicator
          phase={phase}
          published={Boolean(published)}
          publishReady={publishReady}
          onNavigatePhase={onNavigatePhase}
          canNavigatePhase={canNavigatePhase}
        />
      ) : null}
    </header>
  );
}

function PublishedModelToolbar({
  activeTab,
  setActiveTab,
  inputDirty,
  onRerun,
  onEnterDevelopment
}: {
  activeTab: ActiveTab;
  setActiveTab?: (tab: ActiveTab) => void;
  inputDirty: boolean;
  onRerun?: () => void;
  onEnterDevelopment?: () => void;
}) {
  function toggleMenu(event: React.MouseEvent<HTMLElement>) {
    event.preventDefault();
    const current = event.currentTarget.closest("details") as HTMLDetailsElement | null;
    if (!current) return;
    current.open = !current.open;
  }
  function chooseMenuTab(tab: ActiveTab, event: React.MouseEvent<HTMLButtonElement>) {
    setActiveTab?.(tab);
    const current = event.currentTarget.closest("details") as HTMLDetailsElement | null;
    if (current) current.open = false;
  }
  return (
    <div className="published-operating-toolbar" data-testid="published-operating-toolbar">
      {(["inputs", "model", "results"] as ActiveTab[]).map((tab) => (
        <button key={tab} className={`tab-button compact-header-tab ${activeTab === tab ? "active" : ""}`} type="button" onClick={() => setActiveTab?.(tab)}>
          {tab === "inputs" ? "Input" : tab === "results" ? "Output" : "Model"}
        </button>
      ))}
      <button
        className={`icon-action-button rerun-icon-button ${inputDirty ? "dirty" : ""}`}
        type="button"
        data-testid="header-rerun-button"
        aria-label="Rerun current scenario"
        title="Rerun current scenario"
        disabled={!onRerun}
        onClick={onRerun}
      >
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M21 12a9 9 0 0 1-15.4 6.4M3 12A9 9 0 0 1 18.4 5.6" />
          <path d="M21 4v6h-6M3 20v-6h6" />
        </svg>
      </button>
      <details className="card-secondary-actions header-secondary-actions">
        <summary aria-label="More actions" onClick={toggleMenu}>
          <EllipsisIcon />
        </summary>
        <div className="row-action-menu">
          <button className="secondary-button" type="button" onClick={(event) => chooseMenuTab("checks", event)}>
            <span className="row-action-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M9 11l2 2 4-4" />
                <path d="M5 5h14v14H5z" />
              </svg>
            </span>
            Checks
          </button>
          <button className="secondary-button" type="button" onClick={(event) => {
            const current = event.currentTarget.closest("details") as HTMLDetailsElement | null;
            if (current) current.open = false;
            onEnterDevelopment?.();
          }}>
            <span className="row-action-icon" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="M12 5v14M5 12h14" />
              </svg>
            </span>
            Return to Development Mode
          </button>
        </div>
      </details>
    </div>
  );
}

function EllipsisIcon() {
  return (
    <svg className="dot-menu-icon" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="5" cy="10.5" r="1.8" />
      <circle cx="12" cy="10.5" r="1.8" />
      <circle cx="19" cy="10.5" r="1.8" />
    </svg>
  );
}

export function AccountRail({ theme, setTheme, onHome }: { theme: string; setTheme: (theme: string) => void; onHome?: () => void }) {
  return (
    <aside className="account-rail" data-testid="account-rail" aria-label="Account and shortcuts">
      <button className="rail-home-button" type="button" onClick={onHome} data-testid="home-button" title="Home" aria-label="Home">
        <svg className="rail-home-icon" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8" />
          <path d="M3 10a2 2 0 0 1 .709-1.528l7-6a2 2 0 0 1 2.582 0l7 6A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
        </svg>
      </button>
      <span className="rail-spacer" />
      <ThemeToggle theme={theme} setTheme={setTheme} rail />
    </aside>
  );
}

export function ThemeToggle({ theme, setTheme, rail = false }: { theme: string; setTheme: (theme: string) => void; rail?: boolean }) {
  const isDark = theme === "dark";
  return (
    <button
      className={rail ? "theme-dock rail-theme-toggle" : "theme-dock"}
      type="button"
      data-testid="theme-toggle"
      aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
      title={isDark ? "Switch to light mode" : "Switch to dark mode"}
      onClick={() => setTheme(isDark ? "light" : "dark")}
    >
      {isDark ? (
        <svg className="theme-svg" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2" />
          <path d="M12 20v2" />
          <path d="m4.93 4.93 1.41 1.41" />
          <path d="m17.66 17.66 1.41 1.41" />
          <path d="M2 12h2" />
          <path d="M20 12h2" />
          <path d="m6.34 17.66-1.41 1.41" />
          <path d="m19.07 4.93-1.41 1.41" />
        </svg>
      ) : (
        <svg className="theme-svg" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M20.985 12.486a9 9 0 1 1-9.473-9.472c.405-.022.617.46.402.803a6 6 0 0 0 8.268 8.268c.344-.215.825-.004.803.401" />
        </svg>
      )}
    </button>
  );
}

export function ModelIndexHeader() {
  return (
    <div className="model-index-header" aria-hidden="true">
      <span>Model</span>
      <span>Status</span>
      <span>Last updated</span>
      <span>Actions</span>
    </div>
  );
}

function formatModelUpdatedAt(value?: string | null): string {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(date);
}

export function ModelIndexRow({
  model,
  onOpen,
  onRename,
  onDelete
}: {
  model: ModelManifest;
  onOpen: (modelId: string, mode?: AppMode) => void;
  onRename: (modelId: string, modelName: string) => void;
  onDelete: (modelId: string, modelName: string) => void;
}) {
  const isPublished = model.status === "published";
  function toggleMenu(event: React.MouseEvent<HTMLElement>) {
    event.preventDefault();
    const current = event.currentTarget.closest("details") as HTMLDetailsElement | null;
    if (!current) return;
    const nextOpen = !current.open;
    document.querySelectorAll<HTMLDetailsElement>(".card-secondary-actions[open]").forEach((details) => {
      if (details !== current) details.open = false;
    });
    current.open = nextOpen;
  }
  return (
    <article className="model-index-row">
      <button className="model-index-main" type="button" onClick={() => onOpen(model.model_id, isPublished ? "regular" : "development")}>
        <span>{model.name}</span>
      </button>
      <span className="model-index-status">{formatModelStatus(model)}</span>
      <time className="model-index-updated" dateTime={model.updated_utc || undefined}>{formatModelUpdatedAt(model.updated_utc)}</time>
      <div className="model-index-actions">
        <details className="card-secondary-actions">
          <summary aria-label="More actions" onClick={toggleMenu}>
            <EllipsisIcon />
          </summary>
          <div className="row-action-menu">
            {isPublished ? (
              <button className="secondary-button" type="button" onClick={() => onOpen(model.model_id, "development")}>
                <span className="row-action-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24">
                    <path d="M12 5v14M5 12h14" />
                  </svg>
                </span>
                Return to Development Mode
              </button>
            ) : null}
            <button className="secondary-button" type="button" data-testid={`rename-model-${model.model_id}`} onClick={() => onRename(model.model_id, model.name)}>
              <span className="row-action-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="m15.5 5.5 3 3M4 20l4.5-1 10-10a2.12 2.12 0 0 0-3-3l-10 10L4 20Z" />
                </svg>
              </span>
              Rename
            </button>
            <button className="danger-button" type="button" data-testid={`delete-model-${model.model_id}`} onClick={() => onDelete(model.model_id, model.name)}>
              <span className="row-action-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M4 7h16M10 11v6M14 11v6M6 7l1 14h10l1-14M9 7V4h6v3" />
                </svg>
              </span>
              Delete
            </button>
          </div>
        </details>
      </div>
    </article>
  );
}

function InputReview({
  summary,
  custom,
  inputs,
  onInputChange,
  readOnly
}: {
  summary: InputReviewSummary;
  custom?: boolean;
  inputs?: InputParams;
  onInputChange?: (key: string, value: string) => void;
  readOnly?: boolean;
}) {
  const fields = custom && summary.input_schema?.fields?.length
    ? summary.input_schema.fields
    : [...(summary.canonical_inputs || []), ...(summary.missing_inputs || []), ...(summary.ambiguous_inputs || []), ...(summary.inferred_inputs || [])];
  const [activeTab, setActiveTab] = useState<"provided" | "placeholder" | "missing">(custom ? "provided" : "provided");
  const counts = fields.reduce<Record<string, number>>((acc, item) => {
    const key = fieldProvenance(item);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const reviewItems = fields.filter((item) => fieldProvenance(item) === "placeholder" || fieldProvenance(item) === "defaulted" || fieldProvenance(item) === "review");
  const customTabs = [
    { id: "provided", title: "Provided", items: fields.filter((item) => fieldProvenance(item) === "provided"), empty: "No provided values detected." },
    { id: "placeholder", title: "Placeholder", items: reviewItems, empty: "No placeholders need review." },
    { id: "missing", title: "Missing", items: fields.filter((item) => fieldProvenance(item) === "missing"), empty: "No missing values flagged." }
  ] as const;
  const activeTabItems = customTabs.find((tab) => tab.id === activeTab)?.items || [];
  const firstAvailableTab = customTabs.find((tab) => tab.items.length > 0)?.id;
  useEffect(() => {
    if (custom && activeTabItems.length === 0 && firstAvailableTab && firstAvailableTab !== activeTab) {
      setActiveTab(firstAvailableTab);
    }
  }, [custom, activeTab, activeTabItems.length, firstAvailableTab]);
  return (
    <div className="input-review-grid" data-testid="input-review">
      {!custom ? (
        <div className="provenance-summary" data-testid="provenance-summary">
          {Object.entries(counts).map(([key, count]) => (
            <span key={key} className={`provenance-badge ${key}`}>{key}: {count}</span>
          ))}
        </div>
      ) : null}
      {custom ? (
        <>
          <div className="input-review-tabs" role="tablist" aria-label="Input provenance">
            {customTabs.map((tab) => (
              <button
                key={tab.id}
                className={`tab-button ${activeTab === tab.id && tab.items.length ? "active" : ""} ${tab.items.length ? "" : "empty-tab"}`}
                type="button"
                disabled={!tab.items.length}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.title}
                <span>{tab.items.length}</span>
              </button>
            ))}
          </div>
          {customTabs.map((tab) => activeTab === tab.id ? (
            <InputReviewCard
              key={tab.id}
              title={tab.title}
              items={tab.items}
              emptyLabel={tab.empty}
              inputs={inputs}
              onInputChange={onInputChange}
              readOnly={readOnly}
            />
          ) : null)}
        </>
      ) : (
        <>
          <InputReviewCard title="Inputs" items={summary.canonical_inputs || []} emptyLabel="No inputs yet." />
          <InputReviewCard title="Missing" items={summary.missing_inputs || []} emptyLabel="No missing inputs." />
          <InputReviewCard title="Ambiguous" items={summary.ambiguous_inputs || []} emptyLabel="No ambiguous inputs." />
          <InputReviewCard title="Inferred / Defaulted" items={summary.inferred_inputs || []} emptyLabel="No defaults used." />
        </>
      )}
    </div>
  );
}

function InputReviewCard({
  title,
  items,
  emptyLabel,
  inputs,
  onInputChange,
  readOnly
}: {
  title: string;
  items: InputReviewItem[];
  emptyLabel: string;
  inputs?: InputParams;
  onInputChange?: (key: string, value: string) => void;
  readOnly?: boolean;
}) {
  const editable = Boolean(inputs && onInputChange);
  const renderInputRow = (item: InputReviewItem, index: number) => {
    const path = String(item.path || item.key || "");
    const rawValue = path && inputs ? getByPath(inputs, path) : item.value ?? item.assumed_value ?? "";
    const displayValue = formatEditableInputValue(rawValue, item);
    return (
      <div className="input-review-row" key={`${item.path || item.key || item.label || "input"}-${index}`}>
        <strong>{item.label || inputLabel(String(item.path || item.key || "input"))}</strong>
        {editable && path ? (
          <input
            data-testid={`input-${safeTestId(path)}`}
            value={displayValue}
            readOnly={readOnly}
            onChange={(event) => onInputChange?.(path, event.target.value)}
            aria-label={item.label || inputLabel(path)}
          />
        ) : (
          <span>{displayValue}</span>
        )}
      </div>
    );
  };
  return (
    <article className={`input-review-card ${editable ? "input-review-detail-card" : ""}`}>
      <h3>{title}</h3>
      {items.length === 0 ? <p className="empty-row">{emptyLabel}</p> : null}
      {editable && items.length ? (
        <div className="input-review-group-list">
          {groupInputReviewItems(items).map((group, groupIndex) => (
            <details className="input-review-group" key={group.label} open={groupIndex === 0}>
              <summary>
                <span>{group.label}</span>
                <span>{group.items.length}</span>
              </summary>
              <div className="input-review-rows">
                <VirtualList
                  items={group.items}
                  rowHeight={44}
                  threshold={75}
                  renderItem={renderInputRow}
                />
              </div>
            </details>
          ))}
        </div>
      ) : (
        <div className="input-review-rows">{items.slice(0, 8).map(renderInputRow)}</div>
      )}
    </article>
  );
}

function VirtualList<T>({
  items,
  renderItem,
  rowHeight = 36,
  threshold = 75,
  overscan = 8
}: {
  items: T[];
  renderItem: (item: T, index: number) => ReactNode;
  rowHeight?: number;
  threshold?: number;
  overscan?: number;
}) {
  const [scrollTop, setScrollTop] = useState(0);
  if (items.length <= threshold) return <>{items.map(renderItem)}</>;
  const viewportHeight = Math.min(420, Math.max(rowHeight * 6, rowHeight * 12));
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
  const visibleCount = Math.ceil(viewportHeight / rowHeight) + overscan * 2;
  const visibleItems = items.slice(startIndex, startIndex + visibleCount);
  return (
    <div className="virtual-list-shell">
      <div className="virtual-list" style={{ height: viewportHeight }} onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}>
        <div style={{ height: items.length * rowHeight, position: "relative" }}>
          <div style={{ transform: `translateY(${startIndex * rowHeight}px)` }}>
            {visibleItems.map((item, index) => renderItem(item, startIndex + index))}
          </div>
        </div>
      </div>
    </div>
  );
}

function groupInputReviewItems(items: InputReviewItem[]): { label: string; items: InputReviewItem[] }[] {
  const groups = new Map<string, InputReviewItem[]>();
  items.forEach((item) => {
    const path = String(item.path || item.key || "");
    const label = inputAreaLabel(path);
    groups.set(label, [...(groups.get(label) || []), item]);
  });
  return Array.from(groups, ([label, groupItems]) => ({ label, items: groupItems }));
}

function inputAreaLabel(path: string): string {
  const lower = path.toLowerCase();
  if (/clinic_be|belgium/.test(lower)) return "Belgium clinic";
  if (/clinic_nl|netherlands/.test(lower)) return "Netherlands clinic";
  if (/acquisition|purchase|close|entry/.test(lower)) return "Acquisition";
  if (/debt|interest|amort|repay/.test(lower)) return "Debt";
  if (/working|receivable|payable|inventory|tax|capex|depreciation/.test(lower)) return "Working capital, tax, and capex";
  if (/return|irr|moic|exit|multiple/.test(lower)) return "Returns";
  if (/synerg|integration|opex|cost|staff|rent|wage/.test(lower)) return "Operating costs and synergies";
  if (/revenue|price|volume|consult|surgery|lab|pharmacy|wellness|subscriber|churn|arpu/.test(lower)) return "Revenue drivers";
  if (/period|year|currency|display|horizon/.test(lower)) return "Model setup";
  const first = path.split(".")[0] || "Other inputs";
  return friendlyLabel(first);
}

function formatEditableInputValue(value: unknown, field?: InputReviewItem): string {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map((item) => formatEditableInputValue(item, field)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "number" && field?.unit === "percent" && field.storage_scale === "decimal" && field.display_scale === "percent") {
    return String(Number((value * 100).toFixed(6)));
  }
  return String(value);
}

function UnitStubNotice() {
  return (
    <div className="openai-notice" data-testid="unit-stub-note">
      Unit-test mode is active. Live product builds require backend OpenAI access.
    </div>
  );
}

function validationCheckCategory(check: { id?: unknown; label?: unknown }): "Artifact presence" | "Structural/accounting" | "Business logic" {
  const text = `${String(check.id || "")} ${String(check.label || "")}`.toLowerCase();
  if (/(artifact|dataset|file|exists|required|output|report|schema|package)/.test(text)) return "Artifact presence";
  if (/(balance|statement|cash flow|income|assets|liabilities|equity|subtotal|tie|reconcile)/.test(text)) return "Structural/accounting";
  return "Business logic";
}

function validationCategoryCounts(rows: { id?: unknown; label?: unknown; passed?: boolean }[]) {
  return rows.reduce<Record<string, { passed: number; total: number }>>((acc, check) => {
    const category = validationCheckCategory(check);
    const current = acc[category] || { passed: 0, total: 0 };
    acc[category] = {
      passed: current.passed + (check.passed ? 1 : 0),
      total: current.total + 1
    };
    return acc;
  }, {});
}

function CheckSummaryPanel({ summary, emptyText, testId }: { summary: CheckSummary | null; emptyText: string; testId: string }) {
  if (!summary) {
    return (
      <div className="validation-summary empty" data-testid={testId}>
        {emptyText}
      </div>
    );
  }
  const rows = Array.isArray(summary.checks)
    ? summary.checks
    : (summary.cases || []).map((item) => ({
        id: item.id || item.case_id || item.label || "stress_case",
        label: formatCheckLabel(item.label || item.case_id || item.id || "Stress case"),
        passed: item.passed
      }));
  const uniqueRows = rows.filter((check, index, all) => all.findIndex((item) => item.id === check.id || item.label === check.label) === index);
  const passedCount = summary.passed_checks ?? rows.filter((check) => check.passed).length;
  const totalCount = summary.total_checks ?? rows.length;
  const categoryCounts = validationCategoryCounts(uniqueRows);
  const reviewRequired = Boolean((summary as Record<string, unknown>).review_required);
  const headline = summary.passed
    ? reviewRequired
      ? "Technical checks passed; business review required"
      : "Technical checks complete; business review required"
    : "Needs review";
  return (
    <div className={`validation-summary ${summary.passed ? "pass" : "fail"}`} data-testid={testId}>
      <strong>{headline}</strong>
      <span>{passedCount} / {totalCount} checks passed</span>
      <div className="validation-category-row" aria-label="Validation check categories">
        {Object.entries(categoryCounts).map(([category, count]) => (
          <span key={category}>{category}: {count.passed}/{count.total}</span>
        ))}
      </div>
      <details>
        <summary>Show validation details</summary>
        <ul>
          {uniqueRows.map((check) => (
            <li key={check.id}>{check.passed ? "Clear" : "Review"} - {formatCheckLabel(check.label)}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export function StatusLine({ statusText, errorText }: { statusText: string; errorText: string }) {
  return (
    <div className="status-line" role="status">
      <span id="run-status-text">{statusText}</span>
      {errorText ? <strong>{errorText}</strong> : null}
    </div>
  );
}



