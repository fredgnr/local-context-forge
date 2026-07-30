import type {
  AppSettings,
  DocPage,
  EmbeddingModel,
  EmbeddingValidation,
  Job,
  KnowledgeGraph,
  Library,
  LintReport,
  Proposal,
  QueryResponse,
  SystemStatus
} from "./types";
import {
  desktopApiBridge,
  MAX_DESKTOP_API_TIMEOUT_MS,
  type DesktopApiMethod,
  type DesktopApiResponse
} from "./desktopBridge";

const configuredBase = import.meta.env.VITE_API_BASE?.trim() ?? "";
export const API_BASE = configuredBase.replace(/\/+$/, "");

function endpoint(path: string) {
  if (API_BASE.endsWith("/api") && path.startsWith("/api/")) {
    return `${API_BASE}${path.slice(4)}`;
  }
  return `${API_BASE}${path}`;
}

type RecordLike = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const EMBEDDING_MODEL_IDS: Record<string, string> = {
  "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf":
    "embeddinggemma-300m-q8",
  "hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf":
    "qwen3-embedding-0.6b-q8"
};

function uiProvider(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const providers: Record<string, string> = {
    codex_cli: "codex",
    cursor_cli: "cursor"
  };
  return providers[value] ?? value;
}

function apiProvider(value: string): string {
  const providers: Record<string, string> = {
    codex: "codex_cli",
    cursor: "cursor_cli"
  };
  return providers[value] ?? value;
}

function asRecord(value: unknown): RecordLike {
  return value && typeof value === "object" ? (value as RecordLike) : {};
}

function pickString(record: RecordLike, ...keys: string[]): string | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.length) return value;
    if (typeof value === "number") return String(value);
  }
}

function pickNumber(record: RecordLike, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) {
      return Number(value);
    }
  }
}

function unwrapList(payload: unknown, ...keys: string[]): unknown[] {
  if (Array.isArray(payload)) return payload;
  const record = asRecord(payload);
  for (const key of keys) {
    if (Array.isArray(record[key])) return record[key] as unknown[];
  }
  return [];
}

function sourceRefs(value: unknown): DocPage["sourceRefs"] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => {
    const record = asRecord(item);
    return {
      path: pickString(record, "path", "file", "source_path") ?? "unknown",
      lineStart: pickNumber(record, "lineStart", "line_start", "start_line"),
      lineEnd: pickNumber(record, "lineEnd", "line_end", "end_line")
    };
  });
}

function formatValidationDetail(value: unknown): string | undefined {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (!Array.isArray(value)) return undefined;

  const messages = value
    .map((item) => {
      if (typeof item === "string") return item.trim();
      const detail = asRecord(item);
      const message = pickString(detail, "msg", "message", "detail");
      if (!message) return "";
      const location = Array.isArray(detail.loc)
        ? detail.loc
            .map(String)
            .filter((part) => !["body", "query", "path"].includes(part))
            .join(".")
        : "";
      return location ? `${location}：${message}` : message;
    })
    .filter(Boolean);

  return messages.length ? messages.join("；") : undefined;
}

export function formatApiError(body: unknown, status: number): string {
  const details = asRecord(body);
  return (
    formatValidationDetail(details.detail) ||
    pickString(details, "detail", "message", "error") ||
    (typeof body === "string" ? body.trim() : "") ||
    `请求失败 (${status})`
  );
}

function desktopMethod(init: RequestInit): DesktopApiMethod {
  const method = (init.method ?? "GET").toUpperCase();
  if (
    method === "GET" ||
    method === "POST" ||
    method === "PATCH"
  ) {
    return method;
  }
  throw new Error(`桌面 API 不支持 ${method} 请求`);
}

function desktopBody(body: BodyInit | null | undefined): unknown {
  if (body === undefined || body === null) return undefined;
  if (typeof body !== "string") {
    throw new Error("桌面 API 只接受 JSON 请求体");
  }
  try {
    return JSON.parse(body) as unknown;
  } catch {
    throw new Error("桌面 API 请求体不是有效 JSON");
  }
}

function validateDesktopResponse(
  response: DesktopApiResponse
): DesktopApiResponse {
  if (
    !response ||
    !Number.isInteger(response.status) ||
    response.status < 100 ||
    response.status > 599
  ) {
    throw new Error("桌面 API 返回了无效响应");
  }
  return response;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = 30_000
): Promise<T> {
  const bridge = desktopApiBridge();
  if (bridge) {
    const response = validateDesktopResponse(
      await bridge.request({
        method: desktopMethod(init),
        path,
        ...(init.body === undefined ? {} : { body: desktopBody(init.body) }),
        timeoutMs: Math.min(timeoutMs, MAX_DESKTOP_API_TIMEOUT_MS)
      })
    );
    if (response.status < 200 || response.status >= 300) {
      throw new ApiError(
        formatApiError(response.body, response.status),
        response.status
      );
    }
    return response.body as T;
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(endpoint(path), {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers
      },
      signal: controller.signal
    });

    const contentType = response.headers.get("content-type") ?? "";
    const body: unknown = contentType.includes("application/json")
      ? await response.json()
      : await response.text();

    if (!response.ok) {
      throw new ApiError(formatApiError(body, response.status), response.status);
    }
    return body as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("请求超时，请检查 API 服务与网络连接");
    }
    if (error instanceof TypeError) {
      throw new Error(`无法连接 API（${API_BASE || "同源 /api"}）`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function normalizeLibrary(value: unknown): Library {
  const record = asRecord(value);
  return {
    id: pickString(record, "id", "library_id", "slug") ?? "",
    name: pickString(record, "name", "title", "slug") ?? "未命名库",
    sourceUrl: pickString(record, "sourceUrl", "source_url", "source", "repo_url", "url"),
    description: pickString(record, "description", "summary"),
    defaultRef: pickString(
      record,
      "defaultRef",
      "default_ref",
      "default_version",
      "ref",
      "branch"
    ),
    version: pickString(record, "version", "latest_version", "default_version"),
    commitSha: pickString(record, "commitSha", "commit_sha", "source_sha", "sha"),
    status: pickString(record, "status"),
    pageCount: pickNumber(record, "pageCount", "page_count", "pages"),
    updatedAt: pickString(record, "updatedAt", "updated_at", "modified_at")
  };
}

export function normalizeJob(value: unknown): Job {
  const record = asRecord(value);
  const rawProgress = pickNumber(record, "progress", "percent", "percentage");
  return {
    id: pickString(record, "id", "job_id") ?? "",
    libraryId: pickString(record, "libraryId", "library_id"),
    libraryName: pickString(record, "libraryName", "library_name"),
    kind: pickString(record, "kind", "type", "job_type"),
    queuePosition: pickNumber(record, "queuePosition", "queue_position"),
    status: pickString(record, "status", "state") ?? "pending",
    progress:
      rawProgress === undefined
        ? undefined
        : rawProgress > 0 && rawProgress < 1
          ? rawProgress * 100
          : rawProgress,
    phase: pickString(record, "phase", "stage", "current_step"),
    message: pickString(record, "message", "detail"),
    error: pickString(record, "error"),
    requestedProvider: pickString(
      record,
      "requestedProvider",
      "requested_provider",
      "provider"
    ),
    effectiveProvider: pickString(
      record,
      "effectiveProvider",
      "effective_provider",
      "actual_provider"
    ),
    fallbackReason: pickString(record, "fallbackReason", "fallback_reason"),
    attempt: pickNumber(record, "attempt", "attempts"),
    cancellable:
      typeof record.cancellable === "boolean" ? record.cancellable : undefined,
    retryable: typeof record.retryable === "boolean" ? record.retryable : undefined,
    createdAt: pickString(record, "createdAt", "created_at"),
    startedAt: pickString(record, "startedAt", "started_at"),
    finishedAt: pickString(record, "finishedAt", "finished_at"),
    updatedAt: pickString(record, "updatedAt", "updated_at")
  };
}

function normalizePage(value: unknown): DocPage {
  const record = asRecord(value);
  const metadata = asRecord(record.metadata);
  return {
    id: pickString(record, "id", "page_id"),
    path: pickString(record, "path", "slug", "file") ?? "unknown.md",
    title: pickString(record, "title", "name") ?? "未命名文档",
    summary: pickString(record, "summary", "description"),
    kind: pickString(record, "kind", "type"),
    tags: Array.isArray(record.tags)
      ? record.tags.map(String)
      : Array.isArray(metadata.tags)
        ? metadata.tags.map(String)
        : [],
    version: pickString(record, "version"),
    sourceSha: pickString(record, "sourceSha", "source_sha", "commit_sha"),
    markdown: pickString(record, "markdown", "body", "content"),
    content: pickString(record, "content", "body", "markdown"),
    sourceRefs: sourceRefs(
      record.sourceRefs ??
        record.source_refs ??
        record.sources ??
        metadata.source_refs ??
        metadata.sourceRefs
    ),
    updatedAt: pickString(record, "updatedAt", "updated_at", "published_at")
  };
}

function normalizeProposal(value: unknown): Proposal {
  const record = asRecord(value);
  const metadata = asRecord(record.metadata);
  return {
    id: pickString(record, "id", "proposal_id") ?? "",
    libraryId: pickString(record, "libraryId", "library_id"),
    title: pickString(record, "title", "name", "path") ?? "未命名提案",
    path: pickString(record, "path"),
    summary: pickString(record, "summary", "description"),
    status: pickString(record, "status", "state") ?? "pending",
    markdown: pickString(record, "markdown", "content", "body"),
    sourceRefs: sourceRefs(
      record.sourceRefs ??
        record.source_refs ??
        record.sources ??
        metadata.source_refs ??
        metadata.sourceRefs
    ),
    createdAt: pickString(record, "createdAt", "created_at")
  };
}

function normalizeSystemStatus(value: unknown): SystemStatus {
  const record = asRecord(value);
  const rawChecks = unwrapList(record.checks ?? record.services, "checks", "services");
  const checks = rawChecks.map((value, index) => {
    const check = asRecord(value);
    const rawStatus = pickString(check, "status", "state") ?? "unknown";
    const defaultLabels: Record<string, string> = {
      database: "SQLite 数据库",
      "host-runner": "本机 CLI Runner",
      qmd: "本地检索",
      embedding: "Embedding 索引"
    };
    const id = pickString(check, "id", "key", "name") ?? `check-${index}`;
    return {
      id,
      label:
        defaultLabels[id] ??
        pickString(check, "label", "name", "title") ??
        "系统检查",
      status:
        rawStatus === "ok" ||
        rawStatus === "online" ||
        rawStatus === "optional"
          ? "ready"
          : rawStatus,
      message: pickString(check, "message", "detail", "description"),
      action: pickString(check, "action", "hint")
    };
  });
  const readyValue = record.ready ?? record.ok ?? record.healthy;
  return {
    ready:
      typeof readyValue === "boolean"
        ? readyValue
        : checks.length > 0 && checks.every((check) => check.status === "ready"),
    initialized:
      typeof record.initialized === "boolean"
        ? record.initialized
        : typeof record.onboarding_complete === "boolean"
          ? record.onboarding_complete
          : undefined,
    version: pickString(record, "version", "app_version"),
    dataDir: pickString(record, "dataDir", "data_dir"),
    checks
  };
}

function normalizeSettings(value: unknown): AppSettings {
  const record = asRecord(asRecord(value).settings ?? value);
  const advanced = asRecord(record.advanced);
  const providerOrder = Array.isArray(record.provider_order)
    ? record.provider_order.map(uiProvider).filter((item): item is string => !!item)
    : [];
  const fallbackEnabled =
    typeof record.fallback_enabled === "boolean"
      ? record.fallback_enabled
      : undefined;
  const rawEmbedding =
    pickString(record, "embeddingModel", "embedding_model", "model") ??
    "embeddinggemma-300m-q8";
  const embeddingModel =
    EMBEDDING_MODEL_IDS[rawEmbedding] ??
    (Object.values(EMBEDDING_MODEL_IDS).includes(rawEmbedding)
      ? rawEmbedding
      : "custom");
  return {
    revision: pickNumber(record, "revision"),
    generator:
      providerOrder[0] ??
      pickString(record, "generator", "defaultGenerator", "default_generator", "provider") ??
      "codex",
    fallbackGenerator:
      fallbackEnabled === false
        ? "none"
        : providerOrder[1] ??
          pickString(
            record,
            "fallbackGenerator",
            "fallback_generator",
            "fallbackProvider",
            "fallback_provider"
          ) ??
          (providerOrder.length ? "none" : "cursor"),
    embeddingModel,
    customEmbeddingModel:
      embeddingModel === "custom"
        ? rawEmbedding
        : pickString(
            record,
            "customEmbeddingModel",
            "custom_embedding_model"
          ),
    advanced: {
      maxConcurrency: pickNumber(
        advanced,
        "maxConcurrency",
        "max_concurrency"
      ) ?? pickNumber(record, "maxConcurrency", "max_concurrency", "concurrency"),
      queryLimit:
        pickNumber(advanced, "queryLimit", "query_limit") ??
        pickNumber(record, "queryLimit", "query_limit")
    }
  };
}

function settingsPayload(settings: AppSettings) {
  const primary = apiProvider(settings.generator);
  const fallback =
    settings.fallbackGenerator !== "none"
      ? apiProvider(settings.fallbackGenerator)
      : undefined;
  const providerOrder = [primary, fallback].filter(
    (value, index, values): value is string =>
      !!value && values.indexOf(value) === index
  );
  return {
    expected_revision: settings.revision,
    provider_order: providerOrder,
    fallback_enabled: providerOrder.length > 1,
    concurrency: settings.advanced?.maxConcurrency ?? 1,
    embedding_model:
      settings.embeddingModel === "custom"
        ? settings.customEmbeddingModel
        : settings.embeddingModel
  };
}

export const api = {
  async health(): Promise<boolean> {
    await request<unknown>("/api/health", {}, 5_000);
    return true;
  },

  async systemStatus(): Promise<SystemStatus> {
    return normalizeSystemStatus(await request<unknown>("/api/system/status", {}, 5_000));
  },

  async settings(): Promise<AppSettings> {
    return normalizeSettings(await request<unknown>("/api/settings"));
  },

  async updateSettings(settings: AppSettings): Promise<AppSettings> {
    const payload = await request<unknown>("/api/settings", {
      method: "PATCH",
      body: JSON.stringify(settingsPayload(settings))
    });
    return normalizeSettings(payload);
  },

  async embeddingModels(): Promise<EmbeddingModel[]> {
    const payload = await request<unknown>("/api/embedding/models");
    return unwrapList(payload, "items", "models", "data").map((value, index) => {
      const model = asRecord(value);
      return {
        id: pickString(model, "id", "model", "name") ?? `model-${index}`,
        model: pickString(model, "model"),
        name: pickString(model, "name", "label", "model", "id") ?? "Embedding 模型",
        provider: pickString(model, "provider"),
        dimensions: pickNumber(model, "dimensions", "dimension", "dims"),
        description: pickString(model, "description", "summary"),
        recommended:
          typeof model.recommended === "boolean" ? model.recommended : undefined,
        available:
          typeof model.available === "boolean"
            ? model.available
            : typeof model.installed === "boolean"
              ? model.installed
              : undefined
      };
    });
  },

  async validateEmbeddingModel(input: {
    model: string;
  }): Promise<EmbeddingValidation> {
    const payload = asRecord(
      await request<unknown>("/api/embedding/models/validate", {
        method: "POST",
        body: JSON.stringify({
          model: input.model
        })
      })
    );
    const preset = asRecord(payload.preset);
    return {
      valid:
        typeof payload.valid === "boolean"
          ? payload.valid
          : typeof payload.ok === "boolean"
            ? payload.ok
            : false,
      message: pickString(payload, "message", "detail"),
      dimensions:
        pickNumber(payload, "dimensions", "dimension", "dims") ??
        pickNumber(preset, "dimensions", "dimension", "dims")
    };
  },

  async rebuild(libraryId?: string, model?: string): Promise<Job> {
    const payload = await request<unknown>("/api/rebuilds", {
      method: "POST",
      body: JSON.stringify({
        library_id: libraryId || undefined,
        model: model || undefined
      })
    });
    return normalizeJob(asRecord(payload).job ?? payload);
  },

  async libraries(): Promise<Library[]> {
    const payload = await request<unknown>("/api/libraries");
    return unwrapList(payload, "items", "libraries", "data").map(normalizeLibrary);
  },

  async createLibrary(input: {
    name?: string;
    sourceUrl: string;
  }): Promise<Library> {
    const inferredName =
      input.sourceUrl
        .replace(/[\\/]+$/, "")
        .split(/[\\/]/)
        .pop()
        ?.replace(/\.git$/i, "") || "local-library";
    const payload = await request<unknown>("/api/libraries", {
      method: "POST",
      body: JSON.stringify({
        name: input.name || inferredName,
        source: input.sourceUrl
      })
    });
    return normalizeLibrary(asRecord(payload).library ?? payload);
  },

  async ingest(
    libraryId: string,
    input: { ref?: string; generator?: string; version?: string }
  ): Promise<Job> {
    const payload = await request<unknown>(
      `/api/libraries/${encodeURIComponent(libraryId)}/ingest`,
      {
        method: "POST",
        body: JSON.stringify({
          ref: input.ref || undefined,
          provider: input.generator || "mock",
          version: input.version || undefined
        })
      },
      60_000
    );
    return normalizeJob(asRecord(payload).job ?? payload);
  },

  async jobs(): Promise<Job[]> {
    const payload = await request<unknown>("/api/jobs");
    return unwrapList(payload, "items", "jobs", "data").map(normalizeJob);
  },

  async job(id: string): Promise<Job> {
    return normalizeJob(await request<unknown>(`/api/jobs/${encodeURIComponent(id)}`));
  },

  async cancelJob(id: string): Promise<Job> {
    const payload = await request<unknown>(
      `/api/jobs/${encodeURIComponent(id)}/cancel`,
      {
        method: "POST"
      }
    );
    return normalizeJob(asRecord(payload).job ?? payload);
  },

  async retryJob(id: string): Promise<Job> {
    const payload = await request<unknown>(
      `/api/jobs/${encodeURIComponent(id)}/retry`,
      {
        method: "POST"
      }
    );
    return normalizeJob(asRecord(payload).job ?? payload);
  },

  async pages(libraryId: string): Promise<DocPage[]> {
    const payload = await request<unknown>(
      `/api/libraries/${encodeURIComponent(libraryId)}/pages`
    );
    return unwrapList(payload, "items", "pages", "documents", "data").map(normalizePage);
  },

  async page(libraryId: string, path: string): Promise<DocPage> {
    const query = new URLSearchParams({ path });
    return normalizePage(
      await request<unknown>(
        `/api/libraries/${encodeURIComponent(libraryId)}/page?${query.toString()}`
      )
    );
  },

  async proposals(libraryId: string): Promise<Proposal[]> {
    const query = new URLSearchParams({ status: "pending" });
    const payload = await request<unknown>(
      `/api/libraries/${encodeURIComponent(libraryId)}/proposals?${query.toString()}`
    );
    return unwrapList(payload, "items", "proposals", "data").map(normalizeProposal);
  },

  async publishProposal(id: string): Promise<void> {
    await request<unknown>(
      `/api/proposals/${encodeURIComponent(id)}/publish`,
      {
        method: "POST"
      },
      1_860_000
    );
  },

  async rejectProposal(id: string): Promise<void> {
    await request<unknown>(`/api/proposals/${encodeURIComponent(id)}/reject`, {
      method: "POST",
      body: JSON.stringify({})
    });
  },

  async query(input: {
    libraryId: string;
    query: string;
    limit?: number;
  }): Promise<QueryResponse> {
    const payload = await request<unknown>(
      "/api/query",
      {
        method: "POST",
        body: JSON.stringify({
          library_id: input.libraryId,
          query: input.query,
          limit: input.limit ?? 8
        })
      },
      660_000
    );
    const record = asRecord(payload);
    const rows = unwrapList(record.hits ?? record.results ?? payload, "items", "hits", "results");
    return {
      answer: pickString(record, "answer", "summary"),
      engine: pickString(record, "engine"),
      hits: rows.map((value) => {
        const hit = asRecord(value);
        return {
          id: pickString(hit, "id"),
          title: pickString(hit, "title", "name", "path") ?? "匹配结果",
          path: pickString(hit, "path", "file"),
          snippet: pickString(hit, "snippet", "text", "excerpt"),
          content: pickString(hit, "content", "markdown", "body"),
          score: pickNumber(hit, "score", "similarity", "rank"),
          sourceRefs: sourceRefs(hit.sourceRefs ?? hit.source_refs ?? hit.sources)
        };
      })
    };
  },

  async graph(libraryId: string): Promise<KnowledgeGraph> {
    const payload = asRecord(
      await request<unknown>(`/api/libraries/${encodeURIComponent(libraryId)}/graph`)
    );
    const nodes = unwrapList(payload.nodes, "nodes");
    const edges = unwrapList(payload.edges ?? payload.links, "edges", "links");
    return {
      nodes: nodes.map((value) => {
        const node = asRecord(value);
        const metadata = asRecord(node.metadata);
        const nodeType = pickString(node, "type");
        return {
          id: pickString(node, "id", "path") ?? "",
          label: pickString(node, "label", "title", "name", "id") ?? "节点",
          kind:
            pickString(metadata, "kind", "type") ??
            pickString(node, "kind") ??
            nodeType,
          group: pickString(node, "group", "category") ?? nodeType,
          path: pickString(node, "path") ?? pickString(metadata, "path"),
          weight: pickNumber(node, "weight", "value", "size")
        };
      }),
      edges: edges.map((value) => {
        const edge = asRecord(value);
        return {
          source: pickString(edge, "source", "from") ?? "",
          target: pickString(edge, "target", "to") ?? "",
          kind: pickString(edge, "kind", "type", "label")
        };
      })
    };
  },

  async lint(libraryId: string): Promise<LintReport> {
    const payload = asRecord(
      await request<unknown>(`/api/libraries/${encodeURIComponent(libraryId)}/lint`, {
        method: "POST"
      })
    );
    const issues = unwrapList(payload.issues, "issues").map((value) => {
      const issue = asRecord(value);
      return {
        code: pickString(issue, "code", "rule"),
        severity: pickString(issue, "severity", "level") ?? "info",
        message: pickString(issue, "message", "detail") ?? "未知问题",
        path: pickString(issue, "path", "file"),
        line: pickNumber(issue, "line", "line_number")
      };
    });
    const errors = pickNumber(payload, "errors", "error_count");
    return {
      ok: typeof payload.ok === "boolean" ? payload.ok : (errors ?? 0) === 0,
      errors,
      warnings: pickNumber(payload, "warnings", "warning_count"),
      issues
    };
  }
};
