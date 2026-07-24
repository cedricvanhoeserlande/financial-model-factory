import { useEffect, useState } from "react";
import {
  amendModelPackage,
  approveModelSpec,
  buildModelPackage,
  createModel,
  generateModelSpec,
  deleteModel,
  listModels,
  openModel,
  publishModel,
  refreshWorkspace,
  renameModel,
  rerunModel,
  sendInputAgentMessage,
  sendReviewAgentMessage
} from "./api";
import type {
  ActiveTab,
  AppMode,
  InputAgentConversation,
  InputParams,
  InputReviewSummary,
  ModelManifest,
  OpenAIState,
  PackageState,
  RunPayload,
  WorkspacePayload
} from "./types";
import { AccountRail, DevelopmentFlow, HeaderBar, ModelIndexHeader, ModelIndexRow, RegularMode, StatusLine } from "./components/WorkspaceComponents";
import {
  type BuildStep,
  type DevPhase,
  BUILD_STEPS,
  getByPath,
  parseInputValue,
  phaseForPackageState,
  setByPath,
  userConversationText,
  formatModelStatus
} from "./utils/viewHelpers";
const EMPTY_OPENAI: OpenAIState = {
  openai_mode: "live",
  may_call_openai: false,
  configured_model: "gpt-5.4-mini",
  api_key_configured: false
};

const EMPTY_PACKAGE_STATE: PackageState = {
  version_id: null,
  canonical_version_id: null,
  status: "not_started",
  status_label: "Not started",
  stages: [],
  human_review_required: false,
  publish_eligible: false,
  artifact_root: "",
  artifact_tree: [],
  selected_artifact: null,
  input_schema: {},
  latest_run_status: "not_started",
  runtime_contract_defect: null,
  compiler_manifest: {},
  source_provenance: {},
  validation_report: {},
  latest_output: {},
  openai_calls: [],
  package_entrypoint: ""
};

const EMPTY_CONVERSATION: InputAgentConversation = {
  messages: [
    {
      role: "assistant",
      content:
        "Tell me what model you want to build, and I will ask focused corporate-finance questions before drafting the model specification."
    }
  ],
  ready_to_draft: false,
  scope_summary_version: 0,
  scope_summary: "No scope captured yet.",
  locked_decisions: [],
  editable_placeholders: [],
  open_questions: ["Describe the business model, entities, drivers, and required outputs."]
};

const EMPTY_REVIEW_CONVERSATION: InputAgentConversation = {
  messages: [
    {
      role: "assistant",
      content:
        "I can explain the current model specification, mappings, inputs, build blockers, and checks. I will point you to structured actions for model changes."
    }
  ],
  ready_to_draft: false,
  scope_summary_version: 0,
  scope_summary: "Review chat is separate from scoping.",
  locked_decisions: [],
  editable_placeholders: [],
  open_questions: []
};

function isDeveloperModel(model: ModelManifest): boolean {
  const artifactKind = String(model.artifact_kind || "").toLowerCase();
  return ["browser_acceptance", "product_acceptance", "developer_test"].includes(artifactKind);
}

const LAST_MODEL_ID_KEY = "modelFactoryLastModelId";
const LAST_MODE_KEY = "modelFactoryLastMode";
const LAST_TAB_KEY = "modelFactoryLastTab";

function clearSavedWorkspace() {
  localStorage.removeItem(LAST_MODEL_ID_KEY);
  localStorage.removeItem(LAST_MODE_KEY);
  localStorage.removeItem(LAST_TAB_KEY);
}

function App() {
  const [models, setModels] = useState<ModelManifest[]>([]);
  const [selectedModel, setSelectedModel] = useState<ModelManifest | null>(null);
  const [mode, setMode] = useState<AppMode>("home");
  const [devPhase, setDevPhase] = useState<DevPhase>("scope_chat");
  const [activeTab, setActiveTab] = useState<ActiveTab>("inputs");
  const [inputParams, setInputParams] = useState<InputParams>({});
  const [inputReview, setInputReview] = useState<InputReviewSummary>({});
  const [latestRun, setLatestRun] = useState<RunPayload | null>(null);
  const [openai, setOpenai] = useState<OpenAIState>(EMPTY_OPENAI);
  const [packageState, setPackageState] = useState<PackageState>(EMPTY_PACKAGE_STATE);
  const [conversation, setConversation] = useState<InputAgentConversation>(EMPTY_CONVERSATION);
  const [reviewConversation, setReviewConversation] = useState<InputAgentConversation>(EMPTY_REVIEW_CONVERSATION);
  const [theme, setTheme] = useState(() => localStorage.getItem("modelFactoryTheme") || "light");
  const [newModelOpen, setNewModelOpen] = useState(false);
  const [newName, setNewName] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatPending, setChatPending] = useState(false);
  const [reviewChatInput, setReviewChatInput] = useState("");
  const [reviewChatPending, setReviewChatPending] = useState(false);
  const [amendmentPending, setAmendmentPending] = useState(false);
  const [buildSteps] = useState<BuildStep[]>(BUILD_STEPS);
  const [inputDirty, setInputDirty] = useState(false);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});
  const [scenarioState, setScenarioState] = useState<"current" | "dirty" | "rerun_complete">("current");
  const [statusText, setStatusText] = useState("Loading local models...");
  const [errorText, setErrorText] = useState("");
  const [factoryOverlayText, setFactoryOverlayText] = useState("");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.body.dataset.theme = theme;
    localStorage.setItem("modelFactoryTheme", theme);
  }, [theme]);

  useEffect(() => {
    void loadInitialWorkspace();
  }, []);

  useEffect(() => {
    if (!selectedModel) return;
    localStorage.setItem(LAST_MODEL_ID_KEY, selectedModel.model_id);
    localStorage.setItem(LAST_MODE_KEY, mode);
    localStorage.setItem(LAST_TAB_KEY, activeTab);
  }, [selectedModel?.model_id, mode, activeTab]);

  function applyWorkspace(payload: WorkspacePayload, phaseOverride?: DevPhase) {
    setSelectedModel(payload.selected_model);
    setInputParams(payload.canonical_inputs || {});
    const review = payload.input_review_summary || {};
    const packageStateInputSchema = payload.package_state?.input_schema;
    setInputReview(
      packageStateInputSchema && Object.keys(packageStateInputSchema).length
        ? { ...review, input_schema: packageStateInputSchema as InputReviewSummary["input_schema"] }
        : review
    );
    setLatestRun(payload.latest_run || null);
    setOpenai(payload.openai || EMPTY_OPENAI);
    setPackageState(payload.package_state || EMPTY_PACKAGE_STATE);
    setConversation(payload.input_agent_conversation || EMPTY_CONVERSATION);
    setReviewConversation(payload.review_agent_conversation || EMPTY_REVIEW_CONVERSATION);
    setInputDirty(false);
    setInputErrors({});
    setScenarioState("current");
    if (phaseOverride) {
      setDevPhase(phaseOverride);
    } else if (payload.selected_model?.status === "published") {
      setDevPhase("review");
    } else {
      setDevPhase(phaseForPackageState(payload.package_state || EMPTY_PACKAGE_STATE));
    }
  }

  async function runAction(label: string, action: () => Promise<void>) {
    setErrorText("");
    setStatusText(label);
    try {
      await action();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      setErrorText(message);
      setStatusText(message);
    }
  }

  async function loadHome() {
    await runAction("Loading model home...", async () => {
      const payload = await listModels();
      setModels(payload.models || []);
      setOpenai(payload.openai || EMPTY_OPENAI);
      clearSavedWorkspace();
      setSelectedModel(null);
      setPackageState(EMPTY_PACKAGE_STATE);
      setConversation(EMPTY_CONVERSATION);
      setReviewConversation(EMPTY_REVIEW_CONVERSATION);
      setMode("home");
      setStatusText("Choose a model or create a new one.");
    });
  }

  async function loadInitialWorkspace() {
    const savedModelId = localStorage.getItem(LAST_MODEL_ID_KEY);
    if (!savedModelId) {
      await loadHome();
      return;
    }
    await runAction("Restoring model...", async () => {
      try {
        const payload = await openModel(savedModelId);
        setModels(payload.models || []);
        applyWorkspace(payload.workspace);
        const savedMode = localStorage.getItem(LAST_MODE_KEY) === "development" ? "development" : payload.model_manifest.status === "published" ? "regular" : "development";
        const savedTabValue = localStorage.getItem(LAST_TAB_KEY);
        const savedTab: ActiveTab = savedTabValue === "results" || savedTabValue === "checks" ? savedTabValue : "inputs";
        setMode(savedMode);
        setActiveTab(savedMode === "regular" ? savedTab : "inputs");
        setStatusText(`${payload.model_manifest.name} restored.`);
      } catch {
        clearSavedWorkspace();
        const payload = await listModels();
        setModels(payload.models || []);
        setOpenai(payload.openai || EMPTY_OPENAI);
        setSelectedModel(null);
        setPackageState(EMPTY_PACKAGE_STATE);
        setConversation(EMPTY_CONVERSATION);
        setReviewConversation(EMPTY_REVIEW_CONVERSATION);
        setMode("home");
        setStatusText("Choose a model or create a new one.");
      }
    });
  }

  async function handleCreateModel(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanName = newName.trim();
    if (!cleanName) {
      setErrorText("Model name is required.");
      return;
    }
    await runAction("Creating model...", async () => {
      const payload = await createModel(cleanName, "");
      setModels(payload.models || []);
      applyWorkspace(payload.workspace, "scope_chat");
      setMode("development");
      setNewName("");
      setNewModelOpen(false);
      setChatInput("");
      setStatusText(`Created ${payload.model_manifest.name}. Start scoping in chat.`);
    });
  }

  async function handleOpenModel(modelId: string, nextMode?: AppMode) {
    await runAction("Opening model...", async () => {
      const payload = await openModel(modelId);
      if (nextMode === "development" && payload.model_manifest.status === "published") {
        applyWorkspace(payload.workspace, "scope_chat");
        setMode("development");
        setActiveTab("inputs");
        setStatusText("Describe the next model build prompt.");
        return;
      }
      applyWorkspace(payload.workspace);
      const resolvedMode = nextMode || (payload.model_manifest.status === "published" ? "regular" : "development");
      setMode(resolvedMode);
      setActiveTab(resolvedMode === "regular" ? "results" : "inputs");
      setStatusText(`${payload.model_manifest.name} opened.`);
    });
  }

  async function handleDeleteModel(modelId: string, modelName: string) {
    const confirmed = window.confirm(`Delete "${modelName}"? This removes the local model and its saved versions.`);
    if (!confirmed) return;
    await runAction("Deleting model...", async () => {
      const payload = await deleteModel(modelId);
      setModels(payload.models || []);
      if (selectedModel?.model_id === modelId) {
        clearSavedWorkspace();
        setSelectedModel(null);
        setLatestRun(null);
        setMode("home");
      }
      setStatusText(`Deleted ${modelName}.`);
    });
  }

  async function handleRenameModel(modelId: string, currentName: string) {
    const nextName = window.prompt("Rename model", currentName)?.trim();
    if (!nextName || nextName === currentName) return;
    await runAction("Renaming model...", async () => {
      const payload = await renameModel(modelId, nextName);
      setModels(payload.models || []);
      if (selectedModel?.model_id === modelId) {
        setSelectedModel((current) => (current ? { ...current, name: nextName } : current));
      }
      setStatusText(`Renamed ${currentName} to ${nextName}.`);
    });
  }

  async function handleSendChat() {
    if (!selectedModel || !chatInput.trim()) return;
    const text = chatInput.trim();
    const modelId = selectedModel.model_id;
    setChatInput("");
    setChatPending(true);
    setConversation((current) => ({
      ...current,
      messages: [
        ...(current.messages || []),
        { role: "user", content: text, created_utc: new Date().toISOString() }
      ]
    }));
    setErrorText("");
    setStatusText("Input Agent is thinking...");
    try {
      const payload = await sendInputAgentMessage(modelId, text);
      applyWorkspace(payload.workspace, "scope_chat");
      setStatusText("Input Agent replied.");
    } catch (error) {
      const message = error instanceof Error && error.name === "AbortError"
        ? "Input Agent took too long to respond. Refreshing saved scope state."
        : error instanceof Error
          ? error.message
          : String(error);
      setErrorText(message);
      setStatusText(message);
      try {
        const fresh = await refreshWorkspace(modelId);
        applyWorkspace(fresh, "scope_chat");
      } catch {
        // Keep the visible error. The next manual refresh will reload the saved model state.
      }
    } finally {
      setChatPending(false);
    }
  }

  async function handleSendReviewChat() {
    if (!selectedModel || !reviewChatInput.trim()) return;
    const text = reviewChatInput.trim();
    const modelId = selectedModel.model_id;
    const phase = devPhase;
    setReviewChatInput("");
    setReviewChatPending(true);
    setReviewConversation((current) => ({
      ...current,
      messages: [
        ...(current.messages || []),
        { role: "user", content: text, created_utc: new Date().toISOString() }
      ]
    }));
    setErrorText("");
    setStatusText("Review Agent is thinking...");
    try {
      const payload = await sendReviewAgentMessage(modelId, text, phase);
      applyWorkspace(payload.workspace, phase);
      setReviewConversation(payload.workspace.review_agent_conversation || payload.workspace.input_agent_conversation || EMPTY_REVIEW_CONVERSATION);
      setStatusText("Review Agent replied.");
    } catch (error) {
      const message = error instanceof Error && error.name === "AbortError"
        ? "Review Agent took too long to respond. Refreshing saved workspace state."
        : error instanceof Error
          ? error.message
          : String(error);
      setErrorText(message);
      setStatusText(message);
      try {
        const fresh = await refreshWorkspace(modelId);
        applyWorkspace(fresh, phase);
      } catch {
        // Keep the visible error. The next manual refresh will reload the saved model state.
      }
    } finally {
      setReviewChatPending(false);
    }
  }

  async function handleBuildModelPackage(prompt: string, openaiBacked = false) {
    if (!selectedModel) return;
    const cleanPrompt = prompt.trim() || chatInput.trim() || userConversationText(conversation) || selectedModel.name || "Build a simple custom financial model.";
    void openaiBacked;
    setFactoryOverlayText("Asking OpenAI for package files");
    await runAction("Building model with OpenAI...", async () => {
      const payload = await buildModelPackage(selectedModel.model_id, cleanPrompt, true);
      applyWorkspace(payload.workspace, "review");
      setChatInput("");
      setActiveTab("results");
      setStatusText("OpenAI returned a package; package checks passed. Technical checks passed; business review required.");
    }).finally(() => setFactoryOverlayText(""));
  }

  async function handleGenerateModelSpec(prompt: string) {
    if (!selectedModel) return;
    const cleanPrompt = prompt.trim() || chatInput.trim() || userConversationText(conversation) || selectedModel.name || "Create a model specification.";
    setFactoryOverlayText("Asking Modeler for model_spec.json");
    await runAction("Generating model specification with OpenAI...", async () => {
      const payload = await generateModelSpec(selectedModel.model_id, cleanPrompt);
      applyWorkspace(payload.workspace, "scope_chat");
      setChatInput("");
      setStatusText("Model specification drafted. Review and approve before package build.");
    }).finally(() => setFactoryOverlayText(""));
  }

  async function handleApproveModelSpec() {
    if (!selectedModel) return;
    await runAction("Approving model specification...", async () => {
      const payload = await approveModelSpec(selectedModel.model_id);
      applyWorkspace(payload.workspace, "scope_chat");
      setStatusText("Model specification approved. Build can now generate the package.");
    });
  }

  async function handlePublish() {
    if (!selectedModel || !packageState.publish_eligible) return;
    await runAction("Publishing model...", async () => {
      const payload = await publishModel(selectedModel.model_id);
      applyWorkspace(payload.workspace, "review");
      setMode("regular");
      setActiveTab("results");
      setStatusText(`Published package ready for business review - ${payload.model_manifest.name}`);
    });
  }

  async function handleAmendPackage(message: string) {
    if (!selectedModel || !message.trim()) return;
    const modelId = selectedModel.model_id;
    setAmendmentPending(true);
    setFactoryOverlayText("Asking Modeler to amend the package");
    await runAction("Amending model package with OpenAI...", async () => {
      const payload = await amendModelPackage(modelId, message.trim());
      applyWorkspace(payload.workspace, "review");
      setActiveTab("results");
      setStatusText("Amendment complete. Checks and Review Agent audit reran.");
    }).finally(() => {
      setAmendmentPending(false);
      setFactoryOverlayText("");
    });
  }

  async function handleEnterDevelopment() {
    if (!selectedModel) return;
    setMode("development");
    setDevPhase("scope_chat");
    setStatusText("Development Mode opened. No new draft has been created; request a revision when ready.");
  }

  async function handleRerun() {
    if (!selectedModel) return;
    if (Object.keys(inputErrors).length) {
      setErrorText("Correct invalid inputs before rerunning the model.");
      setStatusText("Rerun blocked by invalid inputs.");
      return;
    }
    setInputDirty(false);
    await runAction("Rerunning published model locally...", async () => {
      const run = await rerunModel(selectedModel.model_id, selectedModel.current_build_id, inputParams);
      const fresh = await refreshWorkspace(selectedModel.model_id);
      applyWorkspace(fresh, "review");
      setLatestRun(run);
      setInputDirty(false);
      setScenarioState("rerun_complete");
      setStatusText("Rerun complete. OpenAI called: no.");
    });
  }

  function updateInput(key: string, rawValue: string) {
    const field = findInputField(inputReview, key);
    const original = getByPath(inputParams, key);
    const result = parseInputValue(original, rawValue, field);
    if (!result.ok) {
      setInputErrors((current) => ({ ...current, [key]: result.error }));
      return;
    }
    setInputErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
    const parsed = result.value;
    if (Object.is(parsed, original)) return;
    setInputParams((current) => {
      return setByPath(current, key, parsed);
    });
    setInputDirty(true);
    setScenarioState("dirty");
  }

  function findInputField(summary: InputReviewSummary, key: string) {
    const fields = [
      ...(summary.input_schema?.fields || []),
      ...(summary.canonical_inputs || []),
      ...(summary.inferred_inputs || []),
      ...(summary.ambiguous_inputs || []),
      ...(summary.missing_inputs || [])
    ];
    return fields.find((field) => String(field.path || field.key || "") === key);
  }

  function canNavigatePhase(target: DevPhase): boolean {
    if (target === "scope_chat") return true;
    if (target === "input_review") return Boolean(Object.keys(packageState.input_schema || {}).length || Object.keys(inputParams || {}).length);
    if (target === "building") return buildSteps.some((step) => step.state !== "pending");
    if (target === "review") return Boolean(latestRun || Object.keys(packageState.latest_output || {}).length || ["review_ready", "failed_checks", "published"].includes(packageState.status));
    return false;
  }

  function navigatePhase(target: DevPhase) {
    if (!canNavigatePhase(target)) return;
    setMode("development");
    setDevPhase(target);
  }

  if (mode === "home") {
    const productModels = models.filter((model) => !isDeveloperModel(model));
    const developerModels = models.filter(isDeveloperModel);
    return (
      <main className="app-shell" data-testid="model-home">
        <AccountRail theme={theme} setTheme={setTheme} onHome={loadHome} />
        <section className="page-frame home-shell app-content-pane">
          <section className="home-hero">
            <div>
              <h1>Model Factory</h1>
            </div>
            <div className="home-command">
              <button className="primary-button" type="button" data-testid="new-model-button" onClick={() => setNewModelOpen(true)}>
                + New model
              </button>
            </div>
          </section>
          {newModelOpen ? (
            <div className="modal-backdrop" data-testid="new-model-panel">
              <section className="panel modal-panel">
                <form className="new-model-form compact" onSubmit={handleCreateModel}>
                  <label>
                    Model name
                    <input data-testid="new-model-name" value={newName} onChange={(event) => setNewName(event.target.value)} />
                  </label>
                  <div className="button-row">
                    <button className="secondary-button" type="button" onClick={() => setNewModelOpen(false)}>
                      Cancel
                    </button>
                    <button className="primary-button" type="submit" data-testid="create-model-submit" disabled={!newName.trim()} title={!newName.trim() ? "Enter a model name first." : ""}>
                      Create
                    </button>
                  </div>
                </form>
              </section>
            </div>
          ) : null}
          {productModels.length === 0 ? (
            <section className="empty-state home-empty-state" data-testid="empty-model-state">
              <h2>No models yet</h2>
              <p>Create a new model</p>
            </section>
          ) : (
            <section className="model-index-section" data-testid="model-cards" aria-label="Model index">
              <div className="section-heading-row">
                <div>
                  <p className="eyebrow">Models</p>
                  <h2>Local business models</h2>
                </div>
              </div>
              <div className="model-index">
                <ModelIndexHeader />
                {productModels.map((model) => (
                  <ModelIndexRow key={model.model_id} model={model} onOpen={handleOpenModel} onRename={handleRenameModel} onDelete={handleDeleteModel} />
                ))}
              </div>
            </section>
          )}
          <details className="developer-models">
            <summary>Tests</summary>
            <p className="context-note">Developer and browser-test models are separated from the normal product flow.</p>
            {developerModels.length ? (
              <div className="model-index developer-index">
                <ModelIndexHeader />
                {developerModels.map((model) => (
                  <ModelIndexRow key={model.model_id} model={model} onOpen={handleOpenModel} onRename={handleRenameModel} onDelete={handleDeleteModel} />
                ))}
              </div>
            ) : null}
          </details>
        </section>
      </main>
    );
  }

  const selectedModelPublished = selectedModel?.status === "published" || selectedModel?.current_version_state === "published";

  return (
    <main className="app-shell workspace-app-shell" data-testid="workspace-shell">
      <AccountRail theme={theme} setTheme={setTheme} onHome={loadHome} />
      <section className="model-workspace-frame">
        <HeaderBar
          theme={theme}
          setTheme={setTheme}
          compact
          onHome={loadHome}
          phase={devPhase}
          published={selectedModelPublished}
          publishReady={Boolean(!selectedModelPublished && packageState.publish_eligible)}
          modelName={selectedModel?.name}
          statusLabel={selectedModel ? formatModelStatus(selectedModel) : "Draft"}
          activeTab={activeTab}
          setActiveTab={setActiveTab}
          inputDirty={inputDirty}
          onRerun={handleRerun}
          onEnterDevelopment={handleEnterDevelopment}
          onNavigatePhase={navigatePhase}
          canNavigatePhase={canNavigatePhase}
        />
        <section className={`page-frame workspace-wide-shell workspace-content-pane ${mode === "development" ? "development-content-pane" : "regular-content-pane"}`}>
          {mode === "development" ? (
            <DevelopmentFlow
              phase={devPhase}
              model={selectedModel}
              conversation={conversation}
              reviewConversation={reviewConversation}
              chatInput={chatInput}
              setChatInput={setChatInput}
              reviewChatInput={reviewChatInput}
              setReviewChatInput={setReviewChatInput}
              openai={openai}
              chatPending={chatPending}
              reviewChatPending={reviewChatPending}
              packageState={packageState}
              latestRun={latestRun}
              inputParams={inputParams}
              inputReview={inputReview}
              buildSteps={buildSteps}
              onSend={handleSendChat}
              onSendReview={handleSendReviewChat}
              onGenerateModelSpec={handleGenerateModelSpec}
              onApproveModelSpec={handleApproveModelSpec}
              onBuildModelPackage={handleBuildModelPackage}
              onAmendPackage={handleAmendPackage}
              onPublish={handlePublish}
              onInputChange={updateInput}
              amendmentPending={amendmentPending}
            />
          ) : (
            <RegularMode
              selectedModel={selectedModel}
              inputs={inputParams}
              inputReview={inputReview}
              latestRun={latestRun}
              packageState={packageState}
              activeTab={activeTab}
              setActiveTab={setActiveTab}
              onInputChange={updateInput}
              onRerun={handleRerun}
              onEnterDevelopment={handleEnterDevelopment}
              showToolbar
              inputDirty={inputDirty}
              scenarioState={scenarioState}
              inputErrors={inputErrors}
            />
          )}
          {errorText ? <StatusLine statusText={statusText} errorText={errorText} /> : null}
        </section>
      </section>
      {factoryOverlayText ? <FactoryLoadingOverlay message={factoryOverlayText} /> : null}
    </main>
  );
}

function overlayStep(message: string): { current: number; total: number; label: string; prefix: string } {
  const checkpoint = message.match(/checkpoint\s+(\d+)\s+of\s+(\d+)\s*:\s*(.+)$/i);
  if (checkpoint) {
    return {
      current: Number(checkpoint[1]),
      total: Number(checkpoint[2]),
      label: sentenceCase(checkpoint[3]),
      prefix: "Step",
    };
  }
  if (/repair/i.test(message)) {
    return { current: 1, total: 1, label: sentenceCase(message.replace(/^checkpoint\s*/i, "")), prefix: "Repair step" };
  }
  return { current: 1, total: 1, label: sentenceCase(message), prefix: "Step" };
}

function sentenceCase(value: string): string {
  const clean = value.trim().replace(/\s+/g, " ");
  if (!clean) return "Working";
  return `${clean.charAt(0).toUpperCase()}${clean.slice(1)}`;
}

function FactoryLoadingOverlay({ message }: { message: string }) {
  const step = overlayStep(message);
  const progressWidth = `${Math.max(8, Math.min(100, (step.current / step.total) * 100))}%`;
  return (
    <div className="factory-loading-overlay" data-testid="factory-loading-overlay" role="status" aria-live="polite">
      <div className="factory-loading-card">
        <span className="factory-spinner" aria-hidden="true" />
        <div>
          <strong>Model Factory is working</strong>
          <p>{step.prefix} {step.current} of {step.total}: {step.label}</p>
          <div className="factory-progress" aria-hidden="true">
            <span style={{ width: progressWidth }} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
