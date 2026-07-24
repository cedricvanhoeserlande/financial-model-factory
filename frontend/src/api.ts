import type {
  InputParams,
  ModelActionPayload,
  ModelBuildSummary,
  ModelsPayload,
  PackageArtifact,
  RunPayload,
  WorkspacePayload
} from "./types";

async function requestJson<T>(url: string, init?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const timeoutMs = init?.timeoutMs;
  const controller = timeoutMs ? new AbortController() : null;
  const timeoutId = controller ? window.setTimeout(() => controller.abort(), timeoutMs) : null;
  const { timeoutMs: _timeoutMs, signal, ...requestInit } = init || {};
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...requestInit,
    signal: signal || controller?.signal
  }).finally(() => {
    if (timeoutId) window.clearTimeout(timeoutId);
  });
  const text = await response.text();
  let payload: Record<string, unknown> = {};
  if (text) {
    try {
      payload = JSON.parse(text) as Record<string, unknown>;
    } catch {
      payload = { error: text };
    }
  }
  if (!response.ok) {
    throw new Error(typeof payload.error === "string" && payload.error ? payload.error : `Request failed: ${response.status}`);
  }
  return payload as T;
}

export function listModels(): Promise<ModelsPayload> {
  return requestJson<ModelsPayload>("/api/models");
}

export function createModel(name: string, description: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/models/create", {
    method: "POST",
    body: JSON.stringify({ name, description })
  });
}

export function deleteModel(modelId: string): Promise<ModelsPayload> {
  return requestJson<ModelsPayload>("/api/models/delete", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId })
  });
}

export function renameModel(modelId: string, name: string): Promise<ModelsPayload> {
  return requestJson<ModelsPayload>("/api/models/rename", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, name })
  });
}

export function sendInputAgentMessage(modelId: string, message: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/input-agent/message", {
    method: "POST",
    timeoutMs: 120000,
    body: JSON.stringify({ model_id: modelId, message })
  });
}

export function sendReviewAgentMessage(modelId: string, message: string, phase: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/review-agent/message", {
    method: "POST",
    timeoutMs: 120000,
    body: JSON.stringify({ model_id: modelId, message, phase })
  });
}

export function openModel(modelId: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/models/open", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId })
  });
}

export function publishModel(modelId: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/models/publish", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId })
  });
}

export function rerunModel(modelId: string, buildRunId: string | null, inputParams: InputParams): Promise<RunPayload> {
  return requestJson<RunPayload>("/api/run", {
    method: "POST",
    body: JSON.stringify({
      model_id: modelId,
      build_run_id: buildRunId,
      input_params: inputParams,
      change_intent: "input_only"
    })
  });
}

export function reloadLatestRun(modelId: string): Promise<{ run: RunPayload | null; openai_called: boolean }> {
  return requestJson<{ run: RunPayload | null; openai_called: boolean }>(`/api/runs/latest?model_id=${encodeURIComponent(modelId)}`);
}

export function listModelBuilds(modelId: string): Promise<{ builds: ModelBuildSummary[] }> {
  return requestJson<{ builds: ModelBuildSummary[] }>(`/api/builds?model_id=${encodeURIComponent(modelId)}`);
}

export function refreshWorkspace(modelId: string): Promise<WorkspacePayload> {
  return requestJson<ModelActionPayload>("/api/models/open", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId })
  }).then((payload) => payload.workspace);
}

export function buildModelPackage(modelId: string, prompt: string, openaiBacked = false): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/model/build", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, prompt, openai_backed: openaiBacked })
  });
}

export function amendModelPackage(modelId: string, message: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/model/amend", {
    method: "POST",
    timeoutMs: 300000,
    body: JSON.stringify({ model_id: modelId, message })
  });
}

export function generateModelSpec(modelId: string, prompt: string): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/model/spec/generate", {
    method: "POST",
    timeoutMs: 120000,
    body: JSON.stringify({ model_id: modelId, prompt })
  });
}

export function approveModelSpec(modelId: string, modelSpec?: Record<string, unknown>): Promise<ModelActionPayload> {
  return requestJson<ModelActionPayload>("/api/model/spec/approve", {
    method: "POST",
    body: JSON.stringify({ model_id: modelId, model_spec: modelSpec })
  });
}

export function readPackageArtifact(modelId: string, path: string): Promise<{ artifact: PackageArtifact; openai_called: boolean }> {
  return requestJson<{ artifact: PackageArtifact; openai_called: boolean }>(
    `/api/package/artifact?model_id=${encodeURIComponent(modelId)}&path=${encodeURIComponent(path)}`
  );
}

export function packageArchiveUrl(modelId: string): string {
  return `/api/package/archive?model_id=${encodeURIComponent(modelId)}`;
}

export type PaintShowcaseFile = { path: string; bytes: number; kind: string };
export type PaintShowcasePayload = {
  title: string;
  synthetic: boolean;
  inputs: InputParams;
  input_schema: { fields?: Array<Record<string, unknown>> };
  model_files: PaintShowcaseFile[];
  output: Record<string, unknown>;
  checks: Record<string, unknown>;
  limitations: string[];
  openai_called: boolean;
  openai_call_delta: number;
  package_version: string;
};

export function loadPaintShowcase(): Promise<PaintShowcasePayload> {
  return requestJson<PaintShowcasePayload>("/api/showcase/paint");
}

export function rerunPaintShowcase(inputs: InputParams): Promise<{
  output: Record<string, unknown>;
  checks: Record<string, unknown>;
  technical_checks_passed: boolean;
  openai_called: boolean;
  openai_call_delta: number;
  execution_mode: string;
}> {
  return requestJson("/api/showcase/paint/rerun", { method: "POST", body: JSON.stringify({ inputs }) });
}

export function readPaintShowcaseFile(path: string): Promise<{ path: string; content: string; bytes: number; openai_called: boolean }> {
  return requestJson(`/api/showcase/paint/artifact?path=${encodeURIComponent(path)}`);
}

export const paintShowcaseArchiveUrl = "/api/showcase/paint/archive";
