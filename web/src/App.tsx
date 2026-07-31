import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState
} from "react";
import { ApiError, api } from "./api";
import { Icon, type IconName } from "./components/Icon";
import { MarkdownView } from "./components/MarkdownView";
import {
  desktopSourcesBridge,
  desktopUpdateBridge,
  isDesktopRuntime,
  type DesktopLocalSourceSelection,
  type DesktopUpdateStatus
} from "./desktopBridge";
import { McpOnboarding } from "./McpOnboarding";
import type {
  AppSettings,
  EmbeddingModel,
  Job,
  Library,
  LintReport,
  Proposal,
  QueryResponse,
  RunStatus,
  SystemStatus
} from "./types";
import { hasTerminalTransition, isEmptyWikiReport } from "./uiState";

type View = "overview" | "repositories" | "jobs" | "review" | "query" | "settings";
type Notice = { tone: "success" | "error" | "info"; message: string };

const DEFAULT_SETTINGS: AppSettings = {
  providerPolicy: "codex_only",
  cursorFallbackConsent: {
    subject: "cursor_cli_fallback",
    version: 1,
    granted: false,
    grantedAt: null
  },
  generator: "codex",
  fallbackGenerator: "cursor",
  embeddingModel: "embeddinggemma-300m-q8",
  advanced: { maxConcurrency: 1 }
};

const FALLBACK_MODELS: EmbeddingModel[] = [
  {
    id: "embeddinggemma-300m-q8",
    name: "EmbeddingGemma 300M · Q8",
    provider: "QMD · GGUF",
    dimensions: 768,
    description: "M4 Pro 推荐：体积小、代码检索质量好",
    recommended: true
  },
  {
    id: "qwen3-embedding-0.6b-q8",
    name: "Qwen3 Embedding 0.6B · Q8",
    provider: "QMD · GGUF",
    dimensions: 1024,
    description: "多语言备选；英文代码请先用本地查询集做 A/B"
  }
];

const navigation: { id: View; label: string; description: string; icon: IconName }[] = [
  { id: "overview", label: "系统概览", description: "状态与开始使用", icon: "home" },
  { id: "repositories", label: "仓库", description: "提交与采集", icon: "git" },
  { id: "jobs", label: "任务", description: "队列与运行记录", icon: "terminal" },
  { id: "review", label: "审核", description: "发布知识提案", icon: "review" },
  { id: "query", label: "查询", description: "检索已发布知识", icon: "search" },
  { id: "settings", label: "设置", description: "模型与高级选项", icon: "settings" }
];

function getError(error: unknown) {
  return error instanceof Error ? error.message : "发生未知错误";
}

function formatTime(value?: string) {
  if (!value) return "尚无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function statusLabel(status?: RunStatus) {
  const labels: Record<string, string> = {
    queued: "排队中",
    pending: "待处理",
    running: "运行中",
    cancelling: "取消中",
    cancelled: "已取消",
    succeeded: "已完成",
    completed: "已完成",
    failed: "失败",
    published: "已发布",
    rejected: "已拒绝",
    ready: "就绪",
    warning: "需注意",
    error: "异常"
  };
  return labels[(status || "").toLowerCase()] || status || "未知";
}

function isActiveJob(job: Job) {
  return ["queued", "pending", "running", "cancelling"].includes(
    job.status.toLowerCase()
  );
}

function canCancelJob(job: Job) {
  return job.cancellable ?? ["queued", "running", "cancelling"].includes(
    job.status.toLowerCase()
  );
}

function canRetryJob(job: Job) {
  return job.retryable ?? ["failed", "cancelled"].includes(
    job.status.toLowerCase()
  );
}

function StatusPill({ status }: { status?: RunStatus }) {
  const normalized = (status || "unknown").toLowerCase();
  const tone = ["succeeded", "completed", "published", "ready"].includes(normalized)
    ? "success"
    : ["failed", "rejected", "error"].includes(normalized)
      ? "danger"
      : ["running", "cancelling"].includes(normalized)
        ? "running"
        : "muted";
  return (
    <span className={`status-pill status-pill--${tone}`}>
      <i aria-hidden="true" />
      {statusLabel(status)}
    </span>
  );
}

function EmptyState({
  icon,
  title,
  children,
  action
}: {
  icon: IconName;
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <span className="empty-state__icon">
        <Icon name={icon} size={24} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}

function LoadingRows({ count = 3 }: { count?: number }) {
  return (
    <div className="loading-rows" aria-label="正在载入" aria-busy="true">
      {Array.from({ length: count }).map((_, index) => (
        <span key={index} />
      ))}
    </div>
  );
}

function addOrReplaceJob(current: Job[], job: Job) {
  if (!job.id) return current;
  return [job, ...current.filter((item) => item.id !== job.id)];
}

export default function App() {
  const [view, setView] = useState<View>("overview");
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [selectedLibraryId, setSelectedLibraryId] = useState("");
  const [jobs, setJobs] = useState<Job[]>([]);
  const [system, setSystem] = useState<SystemStatus>();
  const [connection, setConnection] = useState<"checking" | "online" | "offline">(
    "checking"
  );
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<Notice>();
  const [createOpen, setCreateOpen] = useState(false);
  const [ingestLibrary, setIngestLibrary] = useState<Library>();
  const [selectedJob, setSelectedJob] = useState<Job>();
  const [jobActionIds, setJobActionIds] = useState<string[]>([]);
  const [rebuildingLibraryId, setRebuildingLibraryId] = useState("");
  const jobsRef = useRef<Job[]>([]);
  const jobsLoaded = useRef(false);
  const jobActionsRef = useRef(new Set<string>());
  const rebuildInFlightRef = useRef(false);

  const showNotice = useCallback((next: Notice) => {
    setNotice(next);
    window.setTimeout(() => setNotice(undefined), 4500);
  }, []);

  const replaceJobs = useCallback((next: Job[]) => {
    jobsRef.current = next;
    setJobs(next);
    setSelectedJob((current) =>
      current ? next.find((item) => item.id === current.id) ?? current : current
    );
  }, []);

  const loadLibraries = useCallback(async () => {
    const next = await api.libraries();
    setLibraries(next);
    setSelectedLibraryId((current) =>
      next.some((item) => item.id === current) ? current : next[0]?.id ?? ""
    );
    return next;
  }, []);

  const loadJobs = useCallback(async () => {
    try {
      const next = await api.jobs();
      const recovered = !jobsLoaded.current;
      const transitioned = hasTerminalTransition(jobsRef.current, next);
      jobsLoaded.current = true;
      replaceJobs(next);
      return recovered || transitioned;
    } catch (error) {
      jobsLoaded.current = false;
      throw error;
    }
  }, [replaceJobs]);

  useEffect(() => {
    let active = true;
    void (async () => {
      const [healthResult, libraryResult, jobsResult, systemResult] =
        await Promise.allSettled([
          api.health(),
          api.libraries(),
          api.jobs(),
          api.systemStatus()
        ]);
      if (!active) return;
      setConnection(healthResult.status === "fulfilled" ? "online" : "offline");
      if (libraryResult.status === "fulfilled") {
        setLibraries(libraryResult.value);
        setSelectedLibraryId(libraryResult.value[0]?.id ?? "");
      } else {
        showNotice({ tone: "error", message: getError(libraryResult.reason) });
      }
      if (jobsResult.status === "fulfilled") {
        jobsLoaded.current = true;
        replaceJobs(jobsResult.value);
      }
      if (systemResult.status === "fulfilled") setSystem(systemResult.value);
      setLoading(false);
    })();
    return () => {
      active = false;
    };
  }, [replaceJobs, showNotice]);

  useEffect(() => {
    let disposed = false;
    let polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      const [healthResult, jobsResult, systemResult] = await Promise.allSettled([
        api.health(),
        loadJobs(),
        api.systemStatus()
      ]);
      if (!disposed) {
        setConnection(healthResult.status === "fulfilled" ? "online" : "offline");
        if (systemResult.status === "fulfilled") setSystem(systemResult.value);
        if (jobsResult.status === "fulfilled" && jobsResult.value) {
          void loadLibraries();
        }
      }
      polling = false;
    };
    const timer = window.setInterval(() => void poll(), 5_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [loadJobs, loadLibraries]);

  const navigate = (next: View) => {
    setView(next);
    setMobileNavOpen(false);
  };

  const startIngest = async (
    library: Library,
    options: { generator: string; ref: string; version?: string }
  ) => {
    try {
      const job = await api.ingest(library.id, options);
      replaceJobs(addOrReplaceJob(jobsRef.current, job));
      showNotice({ tone: "success", message: `${library.name} 已进入采集队列` });
      void loadLibraries();
      return true;
    } catch (error) {
      showNotice({ tone: "error", message: getError(error) });
      return false;
    }
  };

  const operateJob = async (job: Job, action: "cancel" | "retry") => {
    if (jobActionsRef.current.has(job.id)) return;
    if (
      action === "cancel" &&
      !window.confirm(`确定取消任务 ${job.id.slice(0, 10)} 吗？`)
    ) {
      return;
    }
    jobActionsRef.current.add(job.id);
    setJobActionIds(Array.from(jobActionsRef.current));
    try {
      const next =
        action === "cancel" ? await api.cancelJob(job.id) : await api.retryJob(job.id);
      replaceJobs(addOrReplaceJob(jobsRef.current, next));
      setSelectedJob(next);
      showNotice({
        tone: "success",
        message: action === "cancel" ? "已提交取消请求" : "任务已重新入队"
      });
    } catch (error) {
      showNotice({ tone: "error", message: getError(error) });
    } finally {
      jobActionsRef.current.delete(job.id);
      setJobActionIds(Array.from(jobActionsRef.current));
    }
  };

  const selectedLibrary = libraries.find((item) => item.id === selectedLibraryId);
  const title = navigation.find((item) => item.id === view)?.label ?? "系统概览";

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        跳到主要内容
      </a>
      <aside className={`sidebar ${mobileNavOpen ? "is-open" : ""}`}>
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            <Icon name="code" size={19} />
          </span>
          <div>
            <strong>Local Context Forge</strong>
            <span>本地知识控制面</span>
          </div>
        </div>
        <nav className="primary-nav" aria-label="主导航">
          {navigation.map((item) => (
            <button
              key={item.id}
              className={view === item.id ? "is-active" : ""}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => navigate(item.id)}
            >
              <Icon name={item.icon} size={18} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              {item.id === "jobs" && jobs.filter(isActiveJob).length > 0 && (
                <b>{jobs.filter(isActiveJob).length}</b>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar__footer">
          <span className={`connection connection--${connection}`}>
            <i />
            {connection === "online"
              ? "本地 API 已连接"
              : connection === "offline"
                ? "本地 API 未连接"
                : "正在连接"}
          </span>
          <p>数据默认保留在本机。模型连接按你的设置运行。</p>
        </div>
      </aside>
      {mobileNavOpen && (
        <button
          className="sidebar-scrim"
          aria-label="关闭导航"
          onClick={() => setMobileNavOpen(false)}
        />
      )}

      <div className="app-main">
        <header className="topbar">
          <button
            className="mobile-nav-button"
            aria-label="打开导航"
            aria-expanded={mobileNavOpen}
            onClick={() => setMobileNavOpen(true)}
          >
            <Icon name="books" />
          </button>
          <div>
            <span>Local Context Forge</span>
            <strong>{title}</strong>
          </div>
          <div className="topbar__actions">
            <select
              aria-label="当前知识库"
              value={selectedLibraryId}
              onChange={(event) => setSelectedLibraryId(event.target.value)}
            >
              {!libraries.length && <option value="">尚无知识库</option>}
              {libraries.map((library) => (
                <option key={library.id} value={library.id}>
                  {library.name}
                </option>
              ))}
            </select>
            <button
              className="button button--primary"
              onClick={() => setCreateOpen(true)}
            >
              <Icon name="plus" size={16} />
              添加仓库
            </button>
          </div>
        </header>

        <main id="main-content" tabIndex={-1}>
          {view === "overview" && (
            <Overview
              libraries={libraries}
              jobs={jobs}
              selectedLibraryId={selectedLibraryId}
              loading={loading}
              system={system}
              connection={connection}
              onSelect={setSelectedLibraryId}
              onCreate={() => setCreateOpen(true)}
              onIngest={setIngestLibrary}
              onNavigate={navigate}
            />
          )}
          {view === "repositories" && (
            <Repositories
              libraries={libraries}
              selectedLibraryId={selectedLibraryId}
              loading={loading}
              onSelect={setSelectedLibraryId}
              onCreate={() => setCreateOpen(true)}
              onIngest={setIngestLibrary}
              onRebuild={async (library) => {
                if (rebuildInFlightRef.current) return;
                rebuildInFlightRef.current = true;
                setRebuildingLibraryId(library.id);
                try {
                  const job = await api.rebuild(library.id);
                  replaceJobs(addOrReplaceJob(jobsRef.current, job));
                  showNotice({
                    tone: "success",
                    message: job.id
                      ? `${library.name} 已发起全量 Embedding 重建`
                      : `${library.name} 尚无已发布版本，无需重建`
                  });
                } catch (error) {
                  showNotice({ tone: "error", message: getError(error) });
                } finally {
                  rebuildInFlightRef.current = false;
                  setRebuildingLibraryId("");
                }
              }}
              rebuildingLibraryId={rebuildingLibraryId}
            />
          )}
          {view === "jobs" && (
            <JobsWorkspace
              jobs={jobs}
              loading={loading}
              onSelect={setSelectedJob}
              onCancel={(job) => void operateJob(job, "cancel")}
              onRetry={(job) => void operateJob(job, "retry")}
              busyJobIds={jobActionIds}
            />
          )}
          {view === "review" && (
            <ReviewWorkspace
              library={selectedLibrary}
              onNotice={showNotice}
            />
          )}
          {view === "query" && (
            <QueryWorkspace
              libraries={libraries}
              selectedLibraryId={selectedLibraryId}
            />
          )}
          {view === "settings" && (
            <SettingsWorkspace
              libraries={libraries}
              onJob={(job) => replaceJobs(addOrReplaceJob(jobsRef.current, job))}
              onNotice={showNotice}
            />
          )}
        </main>
      </div>

      {createOpen && (
        <CreateLibraryDialog
          onClose={() => setCreateOpen(false)}
          onCreated={async (library, ingestNow, generator, ref) => {
            setLibraries((current) => [
              library,
              ...current.filter((item) => item.id !== library.id)
            ]);
            setSelectedLibraryId(library.id);
            setCreateOpen(false);
            showNotice({ tone: "success", message: `${library.name} 已添加` });
            if (ingestNow) await startIngest(library, { generator, ref });
            void loadLibraries();
          }}
        />
      )}
      {ingestLibrary && (
        <IngestLibraryDialog
          library={ingestLibrary}
          onClose={() => setIngestLibrary(undefined)}
          onSubmit={async (options) => {
            const started = await startIngest(ingestLibrary, options);
            if (started) setIngestLibrary(undefined);
          }}
        />
      )}
      {selectedJob && (
        <JobDetailDialog
          job={selectedJob}
          onClose={() => setSelectedJob(undefined)}
          onCancel={() => void operateJob(selectedJob, "cancel")}
          onRetry={() => void operateJob(selectedJob, "retry")}
          busy={jobActionIds.includes(selectedJob.id)}
        />
      )}
      {notice && (
        <div
          className={`toast toast--${notice.tone}`}
          role={notice.tone === "error" ? "alert" : "status"}
          aria-live={notice.tone === "error" ? "assertive" : "polite"}
        >
          <Icon
            name={notice.tone === "error" ? "x" : notice.tone === "success" ? "check" : "spark"}
            size={17}
          />
          <span>{notice.message}</span>
          <button aria-label="关闭提示" onClick={() => setNotice(undefined)}>
            <Icon name="x" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}

export function Overview({
  libraries,
  jobs,
  selectedLibraryId,
  loading,
  system,
  connection = "online",
  onSelect,
  onCreate,
  onIngest,
  onNavigate
}: {
  libraries: Library[];
  jobs: Job[];
  selectedLibraryId: string;
  loading: boolean;
  system?: SystemStatus;
  connection?: "checking" | "online" | "offline";
  onSelect: (id: string) => void;
  onCreate: () => void;
  onIngest: (library: Library) => void;
  onNavigate: (view: View) => void;
}) {
  const desktopRuntime = isDesktopRuntime();
  const activeJobs = jobs.filter(isActiveJob);
  const failedJobs = jobs.filter((job) => job.status.toLowerCase() === "failed");
  const fallbackChecks = [
    {
      id: "api",
      label: "本地服务",
      status: connection === "online" ? "ready" : connection === "offline" ? "error" : "unknown",
      message: connection === "online" ? "API 响应正常" : "请启动后端服务",
      action: undefined
    },
    {
      id: "repository",
      label: "代码仓库",
      status: libraries.length ? "ready" : "warning",
      message: libraries.length ? `已接入 ${libraries.length} 个仓库` : "还未接入仓库",
      action: undefined
    },
    {
      id: "queue",
      label: "任务队列",
      status: failedJobs.length ? "warning" : "ready",
      message: activeJobs.length ? `${activeJobs.length} 个任务正在处理` : "队列空闲",
      action: undefined
    }
  ];
  const checks = system?.checks.length ? system.checks : fallbackChecks;

  return (
    <div className="page">
      <section className="welcome-card">
        <div>
          <span className="eyebrow">LOCAL SYSTEM CONTROL PLANE</span>
          <h1>{libraries.length ? "你的本地知识系统" : "从一个代码仓库开始"}</h1>
          <p>
            把源码变成可审核、可检索的知识。日常操作保持简单，高级模型和索引选项留在设置中。
          </p>
          <div className="button-row">
            <button className="button button--primary" onClick={onCreate}>
              <Icon name="plus" size={16} />
              添加代码仓库
            </button>
            <button className="button" onClick={() => onNavigate("query")}>
              <Icon name="search" size={16} />
              查询知识
            </button>
          </div>
        </div>
        <div className="system-score">
          <span
            className={`system-score__dot ${
              (system ? system.ready : checks.every((check) => check.status === "ready"))
                ? "is-ready"
                : ""
            }`}
          />
          <strong>
            {(system ? system.ready : checks.every((check) => check.status === "ready"))
              ? "系统已就绪"
              : "需要完成设置"}
          </strong>
          <small>{system?.version ? `Forge ${system.version}` : "本地运行"}</small>
        </div>
      </section>

      <section className="status-grid" aria-label="系统状态">
        {checks.map((check) => (
          <article className="status-card" key={check.id}>
            <StatusPill status={check.status} />
            <h2>{check.label}</h2>
            <p>{check.message || check.action || "状态已确认"}</p>
          </article>
        ))}
      </section>

      {!libraries.length && !loading && (
        <section className="panel onboarding">
          <header className="panel__header">
            <div>
              <span className="eyebrow">首次使用</span>
              <h2>三步建立本地知识库</h2>
            </div>
          </header>
          <ol>
            <li>
              <span>1</span>
              <div>
                <strong>添加仓库</strong>
                <p>
                  {desktopRuntime
                    ? "粘贴公开 GitHub HTTPS 地址，或选择 Mac 上已克隆的仓库。"
                    : "粘贴 Git 地址或填写本地目录。"}
                </p>
              </div>
            </li>
            <li>
              <span>2</span>
              <div><strong>等待采集</strong><p>系统会把任务放入队列并展示实时进度。</p></div>
            </li>
            <li>
              <span>3</span>
              <div><strong>审核并查询</strong><p>确认生成提案后，知识才会进入查询。</p></div>
            </li>
          </ol>
        </section>
      )}

      <div className="dashboard-grid">
        <section className="panel">
          <header className="panel__header">
            <div>
              <span className="eyebrow">仓库</span>
              <h2>最近接入</h2>
            </div>
            <button className="text-button" onClick={() => onNavigate("repositories")}>查看全部</button>
          </header>
          {loading ? <LoadingRows /> : !libraries.length ? (
            <EmptyState icon="git" title="尚无仓库" action={<button className="button button--small" onClick={onCreate}>添加第一个仓库</button>}>
              {desktopRuntime
                ? "支持公开 GitHub HTTPS 地址，以及经系统选择器授权的本地仓库。"
                : "本地目录和远程 Git 地址都可以。"}
            </EmptyState>
          ) : (
            <div className="compact-list">
              {libraries.slice(0, 4).map((library) => (
                <article
                  key={library.id}
                  className={library.id === selectedLibraryId ? "is-selected" : ""}
                >
                  <button
                    className="compact-list__select"
                    onClick={() => onSelect(library.id)}
                    aria-label={`选择 ${library.name}`}
                  >
                    <span className="repo-icon"><Icon name="git" size={17} /></span>
                    <span><strong>{library.name}</strong><small>{library.sourceUrl || library.id}</small></span>
                    <StatusPill status={library.status || (library.version ? "ready" : "pending")} />
                  </button>
                  <button
                    className="icon-button"
                    aria-label={`重新采集 ${library.name}`}
                    onClick={() => onIngest(library)}
                  >
                    <Icon name="refresh" size={16} />
                  </button>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <header className="panel__header">
            <div>
              <span className="eyebrow">队列</span>
              <h2>最近任务</h2>
            </div>
            <button className="text-button" onClick={() => onNavigate("jobs")}>打开任务</button>
          </header>
          {!jobs.length ? (
            <EmptyState icon="terminal" title="队列空闲">添加并采集仓库后，进度会显示在这里。</EmptyState>
          ) : (
            <div className="activity-list">
              {jobs.slice(0, 5).map((job) => (
                <div key={job.id}>
                  <span className="activity-list__line" />
                  <div>
                    <strong>{job.libraryName || job.libraryId || "知识任务"}</strong>
                    <small>{job.phase || job.message || job.kind || "等待调度"}</small>
                  </div>
                  <StatusPill status={job.status} />
                  <time>{formatTime(job.updatedAt || job.createdAt)}</time>
                  {job.error && (
                    <details className="job-error">
                      <summary>错误详情</summary>
                      <p>{job.error}</p>
                      <small>
                        打开重新采集表单，显式选择 provider、ref 与新的 version label。
                      </small>
                    </details>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Repositories({
  libraries,
  selectedLibraryId,
  loading,
  onSelect,
  onCreate,
  onIngest,
  onRebuild,
  rebuildingLibraryId
}: {
  libraries: Library[];
  selectedLibraryId: string;
  loading: boolean;
  onSelect: (id: string) => void;
  onCreate: () => void;
  onIngest: (library: Library) => void;
  onRebuild: (library: Library) => void;
  rebuildingLibraryId: string;
}) {
  const desktopRuntime = isDesktopRuntime();
  return (
    <div className="page">
      <PageHeader
        eyebrow="REPOSITORY SOURCES"
        title="仓库与采集"
        description="添加代码来源，选择提交或分支，然后把采集任务放入本地队列。"
        action={<button className="button button--primary" onClick={onCreate}><Icon name="plus" size={16} />添加仓库</button>}
      />
      <section className="panel">
        {loading ? <LoadingRows count={4} /> : !libraries.length ? (
          <EmptyState icon="git" title="还没有仓库" action={<button className="button button--primary" onClick={onCreate}>提交第一个仓库</button>}>
            {desktopRuntime
              ? "支持公开 github.com HTTPS 地址；私有仓库请先克隆到本机，再通过系统选择器授权。"
              : "支持 imports 允许目录中的本地仓库以及受信任的 HTTPS Git 地址。"}
          </EmptyState>
        ) : (
          <div className="repository-grid">
            {libraries.map((library) => (
              <article
                key={library.id}
                className={`repository-card ${library.id === selectedLibraryId ? "is-selected" : ""}`}
              >
                <button className="repository-card__select" onClick={() => onSelect(library.id)}>
                  <span className="repo-icon"><Icon name="git" /></span>
                  <span>
                    <strong>{library.name}</strong>
                    <small>{library.sourceUrl || library.id}</small>
                  </span>
                  <StatusPill status={library.status || (library.version ? "ready" : "pending")} />
                </button>
                <dl>
                  <div><dt>当前版本</dt><dd>{library.version || library.defaultRef || "尚未采集"}</dd></div>
                  <div><dt>提交</dt><dd><code>{library.commitSha?.slice(0, 10) || "—"}</code></dd></div>
                  <div><dt>知识页</dt><dd>{library.pageCount ?? "—"}</dd></div>
                  <div><dt>最近更新</dt><dd>{formatTime(library.updatedAt)}</dd></div>
                </dl>
                <div className="button-row">
                  <button className="button button--small button--primary" aria-label={`重新采集 ${library.name}`} onClick={() => onIngest(library)}>
                    <Icon name="refresh" size={15} />采集新提交
                  </button>
                  <button
                    className="button button--small"
                    title="校验此仓库后重建全部已发布语料"
                    disabled={!!rebuildingLibraryId}
                    onClick={() => onRebuild(library)}
                  >
                    {rebuildingLibraryId === library.id ? "正在提交…" : "发起全量重建"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function JobsWorkspace({
  jobs,
  loading,
  onSelect,
  onCancel,
  onRetry,
  busyJobIds
}: {
  jobs: Job[];
  loading: boolean;
  onSelect: (job: Job) => void;
  onCancel: (job: Job) => void;
  onRetry: (job: Job) => void;
  busyJobIds: string[];
}) {
  const [filter, setFilter] = useState<"all" | "active" | "failed">("all");
  const visible = jobs.filter((job) =>
    filter === "active" ? isActiveJob(job) : filter === "failed" ? job.status === "failed" : true
  );
  return (
    <div className="page">
      <PageHeader
        eyebrow="LOCAL JOB QUEUE"
        title="任务队列"
        description="查看采集和索引构建进度。失败任务可以在保留原始参数的前提下重试。"
      />
      <section className="panel">
        <div className="toolbar">
          <div className="segmented" aria-label="任务筛选">
            {(["all", "active", "failed"] as const).map((value) => (
              <button key={value} className={filter === value ? "is-active" : ""} onClick={() => setFilter(value)}>
                {value === "all" ? "全部" : value === "active" ? "处理中" : "失败"}
              </button>
            ))}
          </div>
          <span className="muted-label">每 5 秒自动刷新</span>
        </div>
        {loading ? <LoadingRows count={5} /> : !visible.length ? (
          <EmptyState icon="terminal" title="没有符合条件的任务">新采集或重建任务会出现在这里。</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr><th>任务</th><th>仓库</th><th>阶段与进度</th><th>状态</th><th>更新时间</th><th><span className="sr-only">操作</span></th></tr>
              </thead>
              <tbody>
                {visible.map((job) => (
                  <tr key={job.id}>
                    <td><button className="job-link" onClick={() => onSelect(job)}><code>{job.id.slice(0, 12)}</code><small>{job.kind || "ingest"}{job.queuePosition ? ` · 队列 #${job.queuePosition}` : ""}</small></button></td>
                    <td>{job.libraryName || job.libraryId || "—"}</td>
                    <td>
                      <strong className="phase-label">{job.phase || job.message || "等待调度"}</strong>
                      <div
                        className="progress"
                      >
                        <progress
                          aria-label={`${job.id} 任务进度`}
                          max={100}
                          value={
                            job.progress === undefined
                              ? undefined
                              : Math.min(100, Math.max(0, job.progress))
                          }
                        />
                        <small>{job.progress === undefined ? "—" : `${Math.round(job.progress)}%`}</small>
                      </div>
                    </td>
                    <td><StatusPill status={job.status} /></td>
                    <td>{formatTime(job.updatedAt || job.createdAt)}</td>
                    <td>
                      <div className="row-actions">
                        {canCancelJob(job) && <button className="text-button text-button--danger" disabled={busyJobIds.includes(job.id)} onClick={() => onCancel(job)}>取消</button>}
                        {canRetryJob(job) && <button className="text-button" disabled={busyJobIds.includes(job.id)} onClick={() => onRetry(job)}>重试</button>}
                        <button className="text-button" onClick={() => onSelect(job)}>详情</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function JobDetailDialog({
  job,
  onClose,
  onCancel,
  onRetry,
  busy
}: {
  job: Job;
  onClose: () => void;
  onCancel: () => void;
  onRetry: () => void;
  busy: boolean;
}) {
  return (
    <Dialog title={`任务 ${job.id.slice(0, 12)}`} onClose={onClose}>
      <div className="job-detail">
        <div className="job-detail__header"><StatusPill status={job.status} /><span>{job.kind || "ingest"}</span></div>
        <dl>
          <div><dt>完整 ID</dt><dd><code>{job.id}</code></dd></div>
          <div><dt>知识库</dt><dd>{job.libraryName || job.libraryId || "—"}</dd></div>
          <div><dt>当前阶段</dt><dd>{job.phase || "等待调度"}</dd></div>
          <div><dt>进度</dt><dd>{job.progress === undefined ? "—" : `${Math.round(job.progress)}%`}</dd></div>
          <div><dt>队列位置</dt><dd>{job.queuePosition ? `#${job.queuePosition}` : "—"}</dd></div>
          <div><dt>生成器</dt><dd>{job.effectiveProvider || job.requestedProvider || "—"}{job.fallbackReason ? "（已 fallback）" : ""}</dd></div>
          <div><dt>尝试次数</dt><dd>{job.attempt ?? 1}</dd></div>
          <div><dt>创建时间</dt><dd>{formatTime(job.createdAt)}</dd></div>
          <div><dt>开始时间</dt><dd>{formatTime(job.startedAt)}</dd></div>
          <div><dt>完成时间</dt><dd>{formatTime(job.finishedAt)}</dd></div>
          <div><dt>更新时间</dt><dd>{formatTime(job.updatedAt)}</dd></div>
        </dl>
        {(job.error || job.message) && (
          <div className={job.error ? "error-box" : "info-box"}>
            <strong>{job.error ? "错误详情" : "任务消息"}</strong>
            <p>{job.error || job.message}</p>
          </div>
        )}
        <div className="dialog__actions">
          <button className="button" onClick={onClose}>关闭</button>
          {canCancelJob(job) && <button className="button button--danger" disabled={busy} onClick={onCancel}>{busy ? "处理中…" : "取消任务"}</button>}
          {canRetryJob(job) && <button className="button button--primary" disabled={busy} onClick={onRetry}>{busy ? "处理中…" : "重新入队"}</button>}
        </div>
      </div>
    </Dialog>
  );
}

function ReviewWorkspace({
  library,
  onNotice
}: {
  library?: Library;
  onNotice: (notice: Notice) => void;
}) {
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [selected, setSelected] = useState<Proposal>();
  const [lint, setLint] = useState<LintReport>();
  const [loading, setLoading] = useState(false);
  const [actingProposalId, setActingProposalId] = useState("");
  const actionInFlight = useRef(false);

  const load = useCallback(async () => {
    if (!library) {
      setProposals([]);
      setSelected(undefined);
      return;
    }
    setLoading(true);
    try {
      const next = await api.proposals(library.id);
      setProposals(next);
      setSelected((current) => next.find((item) => item.id === current?.id) ?? next[0]);
    } catch (error) {
      onNotice({ tone: "error", message: getError(error) });
    } finally {
      setLoading(false);
    }
  }, [library, onNotice]);

  useEffect(() => {
    void load();
  }, [load]);

  const act = async (proposal: Proposal, action: "publish" | "reject") => {
    if (actionInFlight.current) return;
    if (action === "reject" && !window.confirm(`确定拒绝“${proposal.title}”吗？`)) return;
    actionInFlight.current = true;
    setActingProposalId(proposal.id);
    try {
      if (action === "publish") await api.publishProposal(proposal.id);
      else await api.rejectProposal(proposal.id);
      onNotice({
        tone: "success",
        message:
          action === "publish"
            ? "本提案已批准；同一版本全部批准后自动激活"
            : "提案已拒绝"
      });
      await load();
    } catch (error) {
      onNotice({ tone: "error", message: getError(error) });
    } finally {
      actionInFlight.current = false;
      setActingProposalId("");
    }
  };

  return (
    <div className="page">
      <PageHeader
        eyebrow="HUMAN REVIEW"
        title="审核知识提案"
        description="生成内容不会自动进入查询。先检查来源与内容，再批准发布。"
        action={<button className="button" disabled={!library || loading} onClick={async () => {
          if (!library) return;
          setLoading(true);
          try {
            const report = await api.lint(library.id);
            setLint(report);
          } catch (error) {
            onNotice({ tone: "error", message: getError(error) });
          } finally {
            setLoading(false);
          }
        }}><Icon name="lint" size={16} />运行校验</button>}
      />
      {lint && <LintBanner report={lint} />}
      {!library ? (
        <section className="panel"><EmptyState icon="review" title="请先选择仓库">添加或在顶部选择一个仓库后查看提案。</EmptyState></section>
      ) : loading && !proposals.length ? <section className="panel"><LoadingRows count={4} /></section> : !proposals.length ? (
        <section className="panel"><EmptyState icon="check" title="没有待审核提案">当前队列已处理完毕，采集新提交后再来看看。</EmptyState></section>
      ) : (
        <div className="review-layout">
          <section className="panel proposal-list">
            <header className="panel__header"><div><span className="eyebrow">{library.name}</span><h2>{proposals.length} 项待审核</h2></div></header>
            {proposals.map((proposal) => (
              <button key={proposal.id} className={selected?.id === proposal.id ? "is-selected" : ""} onClick={() => setSelected(proposal)}>
                <span><strong>{proposal.title}</strong><small>{proposal.path || proposal.summary || "生成提案"}</small></span>
                <Icon name="chevron" size={15} />
              </button>
            ))}
          </section>
          <article className="panel proposal-detail">
            {selected && <>
              <header><div><span className="eyebrow">提案预览</span><h2>{selected.title}</h2><code>{selected.path}</code></div><StatusPill status={selected.status} /></header>
              <div className="markdown-surface"><MarkdownView source={selected.markdown || selected.summary || "暂无预览内容"} /></div>
              {!!selected.sourceRefs?.length && <div className="source-list"><strong>来源</strong>{selected.sourceRefs.map((ref, index) => <code key={`${ref.path}-${index}`}>{ref.path}{ref.lineStart ? `:${ref.lineStart}${ref.lineEnd ? `-${ref.lineEnd}` : ""}` : ""}</code>)}</div>}
              <footer><button className="button button--danger-subtle" disabled={!!actingProposalId} onClick={() => void act(selected, "reject")}>拒绝</button><button className="button button--primary" disabled={!!actingProposalId} onClick={() => void act(selected, "publish")}><Icon name="check" size={16} />{actingProposalId === selected.id ? "处理中…" : "批准发布"}</button></footer>
            </>}
          </article>
        </div>
      )}
    </div>
  );
}

export function LintBanner({ report }: { report: LintReport }) {
  const empty = isEmptyWikiReport(report);
  return (
    <div className={`lint-banner ${empty ? "lint-banner--neutral" : report.ok ? "lint-banner--success" : "lint-banner--warning"}`}>
      <Icon name={report.ok && !empty ? "check" : "lint"} size={18} />
      <div>
        <strong>{empty ? "暂无已发布页面可校验" : report.ok ? "Wiki 校验通过" : `发现 ${report.issues.length} 个问题`}</strong>
        <span>{empty ? "批准提案后可运行完整校验。" : report.ok ? "来源引用和文档结构符合要求。" : report.issues[0]?.message}</span>
      </div>
    </div>
  );
}

export function QueryWorkspace({
  libraries,
  selectedLibraryId
}: {
  libraries: Library[];
  selectedLibraryId: string;
}) {
  const [libraryId, setLibraryId] = useState(selectedLibraryId);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<QueryResponse>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const sequence = useRef(0);

  useEffect(() => {
    sequence.current += 1;
    setLibraryId(selectedLibraryId);
    setResult(undefined);
    setError("");
  }, [selectedLibraryId]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!libraryId || !query.trim()) return;
    const requestId = ++sequence.current;
    setLoading(true);
    setResult(undefined);
    setError("");
    try {
      const next = await api.query({ libraryId, query: query.trim(), limit: 8 });
      if (sequence.current === requestId) setResult(next);
    } catch (requestError) {
      if (sequence.current === requestId) setError(getError(requestError));
    } finally {
      if (sequence.current === requestId) setLoading(false);
    }
  };

  return (
    <div className="page">
      <PageHeader eyebrow="PUBLISHED KNOWLEDGE" title="查询知识" description="用自然语言查询已审核发布的知识，并保留每条答案的源码来源。" />
      <form className="query-box" onSubmit={submit}>
        <label htmlFor="query-text">你想了解这个代码库的什么？</label>
        <div>
          <Icon name="search" size={20} />
          <textarea id="query-text" rows={3} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：如何初始化客户端并配置重试？" onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") event.currentTarget.form?.requestSubmit();
          }} />
        </div>
        <footer>
          <select aria-label="查询知识库" value={libraryId} onChange={(event) => {
            sequence.current += 1;
            setLibraryId(event.target.value);
            setResult(undefined);
            setError("");
          }}>
            {!libraries.length && <option value="">请先添加仓库</option>}
            {libraries.map((library) => <option key={library.id} value={library.id}>{library.name} · {library.version || "latest"}</option>)}
          </select>
          <span>Ctrl / ⌘ + Enter</span>
          <button className="button button--primary" disabled={!libraryId || !query.trim() || loading}>{loading ? "查询中…" : "查询"}</button>
        </footer>
      </form>
      {error && <div className="inline-error" role="alert"><Icon name="lint" /><div><strong>查询失败</strong><span>{error}</span></div></div>}
      {result && (
        <section className="query-results" aria-live="polite">
          <header><div><span className="eyebrow">RESULT</span><h2>查询结果</h2></div><span>{result.engine || "local"} · {result.hits.length} 条命中</span></header>
          {result.answer && <article className="answer-card"><Icon name="spark" /><div><span className="eyebrow">综合回答</span><MarkdownView source={result.answer} /></div></article>}
          {!result.hits.length ? <EmptyState icon="search" title="没有匹配结果">尝试 API 名称、文件名，或先批准待审核提案。</EmptyState> : (
            <div className="hit-list">
              {result.hits.map((hit, index) => <article className="hit-card" key={hit.id || `${hit.path}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div><header><strong>{hit.title}</strong>{hit.score !== undefined && <small>{hit.score.toFixed(3)}</small>}</header>{hit.path && <code>{hit.path}</code>}<p>{hit.snippet || hit.content || "无摘要"}</p>{!!hit.sourceRefs?.length && <div className="source-list">{hit.sourceRefs.map((ref, refIndex) => <code key={`${ref.path}-${refIndex}`}>{ref.path}{ref.lineStart ? `:${ref.lineStart}` : ""}</code>)}</div>}</div></article>)}
            </div>
          )}
        </section>
      )}
    </div>
  );
}

function updateStateLabel(status: DesktopUpdateStatus): string {
  const labels: Record<DesktopUpdateStatus["state"], string> = {
    unavailable: "此构建不可检查更新",
    idle: "尚未检查",
    checking: "正在检查签名更新",
    "up-to-date": "已是当前 channel 的最新版本",
    available: "有可用更新",
    downloading: "正在下载并校验 DMG",
    ready: "DMG 已校验",
    opening: "正在打开已校验 DMG",
    opened: "已打开 DMG",
    error: "更新操作失败"
  };
  return labels[status.state];
}

export function DesktopUpdatePanel() {
  const [status, setStatus] = useState<DesktopUpdateStatus>();
  const [actionError, setActionError] = useState("");
  const [bridgeUnavailable, setBridgeUnavailable] = useState(false);

  useEffect(() => {
    let active = true;
    let unsubscribe: () => void = () => undefined;
    try {
      const bridge = desktopUpdateBridge();
      if (!bridge) {
        setBridgeUnavailable(true);
        return;
      }
      unsubscribe = bridge.subscribe((next) => {
        if (active) setStatus(next);
      });
      void bridge
        .status()
        .then((next) => {
          if (active) setStatus(next);
        })
        .catch(() => {
          if (active) setBridgeUnavailable(true);
        });
    } catch {
      setBridgeUnavailable(true);
    }
    return () => {
      active = false;
      unsubscribe();
    };
  }, []);

  const act = async (
    operation: "check" | "download" | "cancel" | "release"
  ) => {
    setActionError("");
    try {
      const bridge = desktopUpdateBridge();
      if (!bridge) throw new Error("unavailable");
      const next =
        operation === "check"
          ? await bridge.check()
          : operation === "download"
            ? await bridge.downloadOrOpen()
            : operation === "cancel"
              ? await bridge.cancel()
              : await bridge.openReleasePage();
      setStatus(next);
    } catch {
      setActionError(
        operation === "release"
          ? "无法打开官方 Release 页面，请稍后重试。"
          : operation === "cancel"
            ? "取消未完成；退出应用会再次终止并清理 partial 下载。"
            : "操作失败。不会打开或安装未经校验的文件。"
      );
    }
  };

  const busy =
    status?.state === "checking" ||
    status?.state === "downloading" ||
    status?.state === "opening";
  const progress = status?.progress
    ? Math.min(
        100,
        Math.floor(
          (status.progress.receivedBytes / status.progress.totalBytes) * 100
        )
      )
    : undefined;

  return (
    <section className="panel settings-section update-settings">
      <header className="panel__header">
        <div>
          <h2>应用更新</h2>
          <p>只信任内置 Ed25519 公钥验证的 canonical manifest 与 DMG 摘要。</p>
        </div>
      </header>
      <div className="update-policy">
        <span className="status-pill status-pill--muted">
          <i aria-hidden="true" />
          自动应用未交付
        </span>
        <p>
          VAL-UPDATE-001 的物理 0.0.1 → 0.0.2 门禁尚未通过。应用不会静默安装、
          替换当前 App、运行 ZIP、重启或删除数据。
        </p>
      </div>
      {bridgeUnavailable || !status ? (
        <p role="status">
          {bridgeUnavailable ? "此桌面构建无法使用更新检查。" : "正在读取更新状态…"}
        </p>
      ) : (
        <div className="update-status" aria-live="polite">
          <div>
            <strong>{updateStateLabel(status)}</strong>
            <small>
              当前 {status.currentVersion} · {status.channel} channel
              {status.availableVersion
                ? ` · 可用 ${status.availableVersion}`
                : ""}
            </small>
          </div>
          {progress !== undefined && (
            <div
              className="update-progress"
            >
              <progress
                aria-label="DMG 下载进度"
                max={100}
                value={progress}
              />
              <small>{progress}%</small>
            </div>
          )}
          {status.state === "opened" && (
            <p>
              请在系统打开的 DMG 中手动拖拽替换应用；本应用不会代替你执行安装。
            </p>
          )}
          {status.errorCode && (
            <p className="inline-error">
              更新失败（{status.errorCode}）。未经验证的文件未被打开。
            </p>
          )}
          <div className="button-row">
            <button
              className="button button--small"
              disabled={!status.canCheck || busy}
              onClick={() => void act("check")}
            >
              {status.state === "checking" ? "检查中…" : "检查更新"}
            </button>
            {status.canDownloadOrOpen && (
              <button
                className="button button--small button--primary"
                disabled={busy}
                onClick={() => void act("download")}
              >
                {status.state === "opened"
                  ? "再次打开已验证 DMG"
                  : "下载并打开已验证 DMG"}
              </button>
            )}
            {busy && status.state !== "opening" && (
              <button
                className="button button--small"
                onClick={() => void act("cancel")}
              >
                取消
              </button>
            )}
            {status.canOpenReleasePage && (
              <button
                className="button button--small"
                disabled={busy}
                onClick={() => void act("release")}
              >
                手动打开官方 Release 页面
              </button>
            )}
          </div>
        </div>
      )}
      {actionError && <p className="inline-error">{actionError}</p>}
    </section>
  );
}

export function SettingsWorkspace({
  libraries,
  onJob,
  onNotice
}: {
  libraries: Library[];
  onJob: (job: Job) => void;
  onNotice: (notice: Notice) => void;
}) {
  const [settings, setSettings] = useState<AppSettings>(DEFAULT_SETTINGS);
  const [models, setModels] = useState<EmbeddingModel[]>(FALLBACK_MODELS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [validating, setValidating] = useState(false);
  const [validation, setValidation] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [rebuildBusy, setRebuildBusy] = useState("");
  const saveInFlight = useRef(false);
  const validationSequence = useRef(0);
  const desktopRuntime = isDesktopRuntime();

  useEffect(() => {
    let active = true;
    void (async () => {
      const [settingsResult, modelResult] = await Promise.allSettled([
        api.settings(),
        api.embeddingModels()
      ]);
      if (!active) return;
      if (settingsResult.status === "fulfilled") setSettings(settingsResult.value);
      if (modelResult.status === "fulfilled" && modelResult.value.length) setModels(modelResult.value);
      setLoading(false);
    })();
    return () => { active = false; };
  }, []);

  const selectedModel =
    settings.embeddingModel === "custom"
      ? settings.customEmbeddingModel || ""
      : settings.embeddingModel;

  const save = async (rebuild: boolean) => {
    if (saveInFlight.current) return;
    if (!selectedModel.trim()) {
      onNotice({ tone: "error", message: "请先选择或填写 Embedding 模型标识" });
      return;
    }
    saveInFlight.current = true;
    setSaving(true);
    let saved: AppSettings;
    try {
      saved = await api.updateSettings(settings);
      setSettings(saved);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          setSettings(await api.settings());
          onNotice({
            tone: "info",
            message: "设置已在其他窗口更新；已载入最新值，请确认后重试"
          });
        } catch (reloadError) {
          onNotice({ tone: "error", message: getError(reloadError) });
        }
      } else {
        onNotice({ tone: "error", message: getError(error) });
      }
      saveInFlight.current = false;
      setSaving(false);
      return;
    }

    if (!rebuild) {
      onNotice({ tone: "success", message: "设置已保存" });
      saveInFlight.current = false;
      setSaving(false);
      return;
    }

    try {
      const job = await api.rebuild(undefined, selectedModel);
      if (job.id) onJob(job);
      onNotice({
        tone: "success",
        message: job.id
          ? "设置已保存，全量索引正在重建"
          : "设置已保存；当前没有已发布版本需要重建"
      });
    } catch (error) {
      onNotice({
        tone: "error",
        message: `设置已保存，但重建未入队：${getError(error)}`
      });
    } finally {
      saveInFlight.current = false;
      setSaving(false);
    }
  };

  return (
    <div className="page settings-page">
      <PageHeader eyebrow="RUNTIME SETTINGS" title="系统设置" description="推荐配置已预先选择。只有需要调整模型、资源或网络端点时才打开高级选项。" />
      {loading ? <section className="panel"><LoadingRows count={5} /></section> : (
        <>
          <section className="panel settings-section">
            <header className="panel__header"><div><span className="step-badge">1</span><h2>知识生成工具</h2><p>采集代码后，用哪个工具生成待审核知识。</p></div></header>
            {desktopRuntime ? <div className="provider-policy">
              <div className="provider-primary">
                <Icon name="terminal" size={18} />
                <span><strong>Codex CLI</strong><small>唯一默认和首选工具。任务开始前会先检查是否已安装并登录。</small></span>
                <b>默认</b>
              </div>
              <label className="provider-consent">
                <input
                  type="checkbox"
                  checked={
                    settings.providerPolicy === "codex_then_cursor" &&
                    settings.cursorFallbackConsent.granted
                  }
                  onChange={(event) => {
                    const granted = event.target.checked;
                    setSettings((current) => ({
                      ...current,
                      providerPolicy: granted
                        ? "codex_then_cursor"
                        : "codex_only",
                      cursorFallbackConsent: {
                        ...current.cursorFallbackConsent,
                        subject: "cursor_cli_fallback",
                        version: 1,
                        granted,
                        grantedAt: granted
                          ? current.cursorFallbackConsent.grantedAt
                          : null
                      }
                    }));
                  }}
                />
                <span>
                  <strong>Codex 预检不可用时，允许改用 Cursor CLI</strong>
                  <small>仅在任务开始前确认 Codex 未安装或未登录时生效。Cursor 会使用你单独登录的 Cursor 账户和额度，不与 Codex 账户或额度共享。</small>
                </span>
              </label>
            </div> : <>
              <div className="choice-grid">
                {[
                  { id: "codex", name: "Codex CLI", text: "适合已配置 Codex 的本地环境。", badge: "推荐" },
                  { id: "cursor", name: "Cursor", text: "使用 legacy Cursor Host Runner。", badge: "备用" },
                  { id: "mock", name: "Mock", text: "确定性测试输出，不用于正式 Wiki。", badge: "测试" },
                  { id: "ollama", name: "Ollama", text: "调用高级用户自行配置的 Ollama 节点。", badge: "高级" }
                ].map((choice) => (
                  <label className={settings.generator === choice.id ? "choice-card is-selected" : "choice-card"} key={choice.id}>
                    <input type="radio" name="generator" value={choice.id} checked={settings.generator === choice.id} onChange={() => setSettings((current) => ({ ...current, generator: choice.id, fallbackGenerator: choice.id === "codex" ? "cursor" : choice.id === "cursor" ? "codex" : "none" }))} />
                    <span><strong>{choice.name}</strong><small>{choice.text}</small></span><b>{choice.badge}</b>
                  </label>
                ))}
              </div>
              <label className="field compact-field"><span>{settings.generator === "cursor" ? "Cursor" : "Codex"} 预检不可用时</span><select disabled={!["codex", "cursor"].includes(settings.generator)} value={["codex", "cursor"].includes(settings.generator) ? settings.fallbackGenerator : "none"} onChange={(event) => setSettings((current) => ({ ...current, fallbackGenerator: event.target.value }))}>{settings.generator === "cursor" ? <option value="codex">使用 Codex CLI</option> : <option value="cursor">使用 Cursor CLI</option>}<option value="none">不使用后备</option></select></label>
            </>}
            {desktopRuntime && <p className="settings-note"><Icon name="terminal" size={16} /><span>一旦 Codex 已确认并提交执行，即使随后超时或失败也绝不会切换到 Cursor，以免重复消耗额度或生成两份冲突结果。</span></p>}
          </section>

          {desktopRuntime && <McpOnboarding />}
          {desktopRuntime && <DesktopUpdatePanel />}

          <section className="panel settings-section">
            <header className="panel__header"><div><span className="step-badge">{desktopRuntime ? "3" : "2"}</span><h2>Embedding 模型</h2><p>决定语义检索的速度、内存占用和效果。</p></div></header>
            <div className="model-grid">
              {models.map((model) => (
                <label className={settings.embeddingModel === model.id ? "model-card is-selected" : "model-card"} key={model.id}>
                  <input type="radio" name="embedding-model" checked={settings.embeddingModel === model.id} onChange={() => setSettings((current) => ({ ...current, embeddingModel: model.id }))} />
                  <span><strong>{model.name}</strong><small>{model.description || model.provider || "本地模型"}</small></span>
                  <span className="model-meta">{model.dimensions ? `${model.dimensions} 维` : model.provider}{model.recommended && <b>推荐</b>}</span>
                </label>
              ))}
              <label className={settings.embeddingModel === "custom" ? "model-card is-selected" : "model-card"}>
                <input type="radio" name="embedding-model" checked={settings.embeddingModel === "custom"} onChange={() => setSettings((current) => ({ ...current, embeddingModel: "custom" }))} />
                <span><strong>自定义模型</strong><small>填写 QMD 可用的 Hugging Face GGUF 标识。</small></span>
              </label>
            </div>
            {settings.embeddingModel === "custom" && <div className="custom-model">
              <label className="field"><span>模型标识</span><input value={settings.customEmbeddingModel || ""} onChange={(event) => setSettings((current) => ({ ...current, customEmbeddingModel: event.target.value }))} placeholder="hf:org/Qwen3-Embedding-repo/model.gguf" /><small>只接受 EmbeddingGemma / Qwen3-Embedding 家族的安全 <code>hf:org/repo/file.gguf</code>，不接受 HTTP endpoint。</small></label>
            </div>}
            <div className="validation-row">
              <button className="button button--small" disabled={!selectedModel || validating} onClick={async () => {
                const requestId = ++validationSequence.current;
                setValidating(true);
                setValidation("");
                try {
                  const result = await api.validateEmbeddingModel({ model: selectedModel });
                  if (requestId === validationSequence.current) {
                    setValidation(result.valid ? `模型标识有效${result.dimensions ? ` · ${result.dimensions} 维` : ""}` : result.message || "模型不可用");
                  }
                } catch (error) {
                  if (requestId === validationSequence.current) {
                    setValidation(getError(error));
                  }
                } finally {
                  if (requestId === validationSequence.current) {
                    setValidating(false);
                  }
                }
              }}>{validating ? "检查中…" : "检查模型标识"}</button>
              {validation && <span role="status">{validation}</span>}
            </div>
          </section>

          <section className="panel settings-section">
            <button className="advanced-toggle" aria-expanded={advancedOpen} onClick={() => setAdvancedOpen((value) => !value)}><span><Icon name="settings" size={18} /><span><strong>运行边界</strong><small>M4 Pro 的稳妥队列设置</small></span></span><Icon name="chevron" size={16} /></button>
            {advancedOpen && <div className="advanced-fields">
              <label className="field"><span>最大并发任务数</span><input type="number" min={1} max={1} disabled value={1} /><small>当前版本固定为 1：保证 Codex/Cursor 调用顺序、审核可追踪，并避免 24 GB 统一内存同时承受生成与 embedding 峰值。</small></label>
            </div>}
          </section>

          <section className="settings-savebar">
            <div><strong>模型变更需要重建索引</strong><span>仅保存不会改变已有索引；“保存并重建”会把所有仓库加入队列。</span></div>
            <div className="button-row"><button className="button" disabled={saving} onClick={() => void save(false)}>仅保存</button><button className="button button--primary" disabled={saving} onClick={() => void save(true)}>{saving ? "处理中…" : "保存并重建全部"}</button></div>
          </section>

          {!!libraries.length && <section className="panel settings-section">
            <header className="panel__header"><div><h2>从指定仓库发起重建</h2><p>用于确认该仓库已有可发布版本；QMD 共享一个模型 profile，因此实际任务仍会校验并重建全部已发布语料，不调用 LLM。</p></div></header>
            <div className="single-rebuild-list">{libraries.map((library) => <div key={library.id}><span><strong>{library.name}</strong><small>{library.version || library.defaultRef || "latest"}</small></span><button className="button button--small" disabled={!!rebuildBusy || saving} onClick={async () => {
              setRebuildBusy(library.id);
              try {
                const job = await api.rebuild(library.id, selectedModel);
                if (job.id) onJob(job);
                onNotice({
                  tone: "success",
                  message: job.id
                    ? `${library.name} 已发起全量 Embedding 重建`
                    : `${library.name} 尚无已发布版本，无需重建`
                });
              } catch (error) {
                onNotice({ tone: "error", message: getError(error) });
              } finally {
                setRebuildBusy("");
              }
            }}>{rebuildBusy === library.id ? "正在提交…" : "从此库发起"}</button></div>)}</div>
          </section>}
        </>
      )}
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return <header className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>{action}</header>;
}

function Dialog({
  title,
  onClose,
  children
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLElement>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    const previousFocus =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = dialogRef.current;
    const focusable = () =>
      Array.from(
        frame?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'
        ) ?? []
      ).filter((element) => !element.hasAttribute("hidden"));

    if (!frame?.querySelector<HTMLElement>("[autofocus]")) {
      focusable()[0]?.focus();
    }

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const items = focusable();
      if (!items.length) {
        event.preventDefault();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("keydown", handleKey);
      previousFocus?.focus();
    };
  }, []);

  return (
    <div className="dialog-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <section ref={dialogRef} className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title">
        <header><h2 id="dialog-title">{title}</h2><button className="icon-button" aria-label="关闭" onClick={onClose}><Icon name="x" size={18} /></button></header>
        {children}
      </section>
    </div>
  );
}

function CreateLibraryDialog({
  onClose,
  onCreated
}: {
  onClose: () => void;
  onCreated: (library: Library, ingestNow: boolean, generator: string, ref: string) => void;
}) {
  const [name, setName] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [localSelection, setLocalSelection] =
    useState<DesktopLocalSourceSelection | null>(null);
  const [ref, setRef] = useState("HEAD");
  const [generator, setGenerator] = useState("auto");
  const [ingestNow, setIngestNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [selectingLocal, setSelectingLocal] = useState(false);
  const [error, setError] = useState("");
  const desktopRuntime = isDesktopRuntime();
  const selectedSource = localSelection?.grantId ?? sourceUrl.trim();

  const selectLocalRepository = async () => {
    setSelectingLocal(true);
    setError("");
    try {
      const selection = await desktopSourcesBridge()?.selectRepository();
      if (selection) {
        setLocalSelection(selection);
        setSourceUrl("");
      }
    } catch (selectionError) {
      setError(getError(selectionError));
    } finally {
      setSelectingLocal(false);
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedSource) return;
    setBusy(true);
    setError("");
    try {
      const library = await api.createLibrary({
        name: name.trim() || localSelection?.displayName || undefined,
        sourceUrl: selectedSource
      });
      await onCreated(library, ingestNow, generator, ref.trim() || "HEAD");
    } catch (submitError) {
      const errorCode =
        submitError &&
        typeof submitError === "object" &&
        "code" in submitError &&
        typeof submitError.code === "string"
          ? submitError.code
          : "";
      const grantCanBeRetried =
        errorCode === "busy" || errorCode === "unavailable";
      if (localSelection && !grantCanBeRetried) {
        setLocalSelection(null);
      }
      setError(
        `${getError(submitError)}${
          localSelection && !grantCanBeRetried
            ? "；本地授权已失效，请重新选择仓库。"
            : ""
        }`
      );
      setBusy(false);
    }
  };

  return (
    <Dialog title="添加代码仓库" onClose={onClose}>
      <form className="form-stack" onSubmit={submit}>
        <p className="dialog-intro">
          {desktopRuntime
            ? "可填写公开 https://github.com/<owner>/<repository>[.git]，或通过系统选择器授权 Mac 上的目录。私有仓库请先用熟悉的 Git 工具克隆到本机；应用不会索取 GitHub 凭据。"
            : "粘贴受信任的 HTTPS Git 地址；本地仓库请先放入安装目录的 imports，再填写容器路径。添加后可以立即开始采集。"}
        </p>
        {desktopRuntime && (
          <div className="local-source-picker">
            <button
              type="button"
              className="button"
              disabled={busy || selectingLocal}
              onClick={selectLocalRepository}
            >
              <Icon name="git" size={15} />
              {selectingLocal
                ? "正在打开选择器…"
                : localSelection
                  ? "改选本地仓库"
                  : "选择本地仓库"}
            </button>
            {localSelection && (
              <div className="local-source-selection" aria-live="polite">
                <span>
                  <strong>已授权本地仓库</strong>
                  <small>{localSelection.displayName}</small>
                </span>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => setLocalSelection(null)}
                >
                  清除
                </button>
              </div>
            )}
            <p className="form-help">
              只向页面返回一次性授权编号和目录名称，不暴露完整路径；授权会在提交后失效。
            </p>
          </div>
        )}
        <label className="field">
          <span>{desktopRuntime ? "公开 GitHub HTTPS 地址（与本地仓库二选一）" : "仓库地址或 imports 路径"} <b>*</b></span>
          <input
            autoFocus={!desktopRuntime}
            required={!localSelection}
            value={sourceUrl}
            onChange={(event) => {
              setSourceUrl(event.target.value);
              setLocalSelection(null);
            }}
            placeholder={
              desktopRuntime
                ? "https://github.com/org/repo.git"
                : "https://github.com/org/repo.git 或 /imports/project"
            }
          />
        </label>
        <label className="field"><span>显示名称（可选）</span><input value={name} onChange={(event) => setName(event.target.value)} placeholder="不填则从仓库地址推断" /></label>
        <details className="form-advanced"><summary>采集选项</summary><div>
          <label className="field"><span>分支、标签或提交</span><input value={ref} onChange={(event) => setRef(event.target.value)} /></label>
          <label className="field"><span>文档生成器</span><select value={generator} onChange={(event) => setGenerator(event.target.value)}><option value="auto">使用系统默认（推荐）</option><option value="codex">只用 Codex CLI</option>{!desktopRuntime && <><option value="cursor">只用 Cursor</option><option value="mock">Mock（测试）</option><option value="ollama">Ollama</option></>}</select></label>
        </div></details>
        <label className="check-field"><input type="checkbox" checked={ingestNow} onChange={(event) => setIngestNow(event.target.checked)} /><span><strong>添加后立即采集</strong><small>任务会进入队列，不会阻塞当前页面。</small></span></label>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="dialog__actions"><button type="button" className="button" onClick={onClose}>取消</button><button className="button button--primary" disabled={busy || selectingLocal || !selectedSource}>{busy ? "正在提交…" : ingestNow ? "添加并采集" : "添加仓库"}</button></div>
      </form>
    </Dialog>
  );
}

function IngestLibraryDialog({
  library,
  onClose,
  onSubmit
}: {
  library: Library;
  onClose: () => void;
  onSubmit: (input: { generator: string; ref: string; version: string }) => Promise<void>;
}) {
  const [ref, setRef] = useState(library.defaultRef || "HEAD");
  const [version, setVersion] = useState("");
  const [generator, setGenerator] = useState("auto");
  const [busy, setBusy] = useState(false);
  const desktopRuntime = isDesktopRuntime();

  return (
    <Dialog title={`重新采集 ${library.name}`} onClose={onClose}>
      <form className="form-stack" onSubmit={async (event) => {
        event.preventDefault();
        setBusy(true);
        await onSubmit({ ref: ref.trim(), version: version.trim(), generator });
        setBusy(false);
      }}>
        <p className="dialog-intro">选择一个确定的提交来源并创建新的不可变知识版本。</p>
        <label className="field"><span>分支、标签或提交 <b>*</b></span><input required value={ref} onChange={(event) => setRef(event.target.value)} /></label>
        <label className="field"><span>新版本标签 <b>*</b></span><input required value={version} onChange={(event) => setVersion(event.target.value)} placeholder="例如：2.0.0 或 2026-07-29" /></label>
        <label className="field"><span>文档生成器 <b>*</b></span><select value={generator} onChange={(event) => setGenerator(event.target.value)}><option value="auto">使用系统默认（推荐）</option><option value="codex">只用 Codex CLI</option>{!desktopRuntime && <><option value="cursor">只用 Cursor</option><option value="mock">Mock（测试）</option><option value="ollama">Ollama</option></>}</select></label>
        <small className="form-help">显式选择默认策略或 Codex，并填写 ref 与新的 version label，确保失败任务可以审计和重现。</small>
        <div className="dialog__actions"><button type="button" className="button" onClick={onClose}>取消</button><button className="button button--primary" disabled={busy || !ref.trim() || !version.trim()}>{busy ? "正在入队…" : "开始采集"}</button></div>
      </form>
    </Dialog>
  );
}
