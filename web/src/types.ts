export type RunStatus =
  | "queued"
  | "pending"
  | "running"
  | "succeeded"
  | "completed"
  | "failed"
  | "rejected"
  | "published"
  | string;

export interface Library {
  id: string;
  name: string;
  sourceUrl?: string;
  description?: string;
  defaultRef?: string;
  version?: string;
  commitSha?: string;
  status?: RunStatus;
  pageCount?: number;
  updatedAt?: string;
}

export interface Job {
  id: string;
  libraryId?: string;
  libraryName?: string;
  kind?: string;
  queuePosition?: number;
  status: RunStatus;
  progress?: number;
  phase?: string;
  message?: string;
  error?: string;
  requestedProvider?: string;
  effectiveProvider?: string;
  fallbackReason?: string;
  attempt?: number;
  cancellable?: boolean;
  retryable?: boolean;
  createdAt?: string;
  startedAt?: string;
  finishedAt?: string;
  updatedAt?: string;
}

export type CheckStatus = "ready" | "warning" | "error" | "unknown" | string;

export interface SystemCheck {
  id: string;
  label: string;
  status: CheckStatus;
  message?: string;
  action?: string;
}

export interface SystemStatus {
  ready: boolean;
  initialized?: boolean;
  version?: string;
  dataDir?: string;
  checks: SystemCheck[];
}

export interface AppSettings {
  revision?: number;
  generator: string;
  fallbackGenerator: string;
  embeddingModel: string;
  customEmbeddingModel?: string;
  advanced?: {
    maxConcurrency?: number;
    queryLimit?: number;
  };
}

export interface EmbeddingModel {
  id: string;
  model?: string;
  name: string;
  provider?: string;
  dimensions?: number;
  description?: string;
  recommended?: boolean;
  available?: boolean;
}

export interface EmbeddingValidation {
  valid: boolean;
  message?: string;
  dimensions?: number;
}

export interface DocPage {
  id?: string;
  path: string;
  title: string;
  summary?: string;
  kind?: string;
  tags?: string[];
  version?: string;
  sourceSha?: string;
  markdown?: string;
  content?: string;
  sourceRefs?: SourceRef[];
  updatedAt?: string;
}

export interface SourceRef {
  path: string;
  lineStart?: number;
  lineEnd?: number;
}

export interface Proposal {
  id: string;
  libraryId?: string;
  title: string;
  path?: string;
  summary?: string;
  status: RunStatus;
  markdown?: string;
  sourceRefs?: SourceRef[];
  createdAt?: string;
}

export interface QueryHit {
  id?: string;
  title: string;
  path?: string;
  snippet?: string;
  content?: string;
  score?: number;
  sourceRefs?: SourceRef[];
}

export interface QueryResponse {
  answer?: string;
  engine?: string;
  hits: QueryHit[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind?: string;
  group?: string;
  path?: string;
  weight?: number;
}

export interface GraphEdge {
  source: string;
  target: string;
  kind?: string;
}

export interface KnowledgeGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface LintIssue {
  code?: string;
  severity: "error" | "warning" | "info" | string;
  message: string;
  path?: string;
  line?: number;
}

export interface LintReport {
  ok: boolean;
  errors?: number;
  warnings?: number;
  issues: LintIssue[];
}
