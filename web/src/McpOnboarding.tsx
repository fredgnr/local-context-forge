import { useCallback, useEffect, useRef, useState } from "react";
import { Icon } from "./components/Icon";
import {
  desktopMcpBridge,
  type DesktopMcpSetupErrorCode,
  type DesktopMcpSetupStatus
} from "./desktopBridge";

type Operation = "refresh" | "configure" | "clear";

const ERROR_MESSAGES: Record<DesktopMcpSetupErrorCode, string> = {
  busy: "另一项 MCP 设置操作正在进行，请稍后重试。",
  "not-installed": "没有找到受支持的 Codex CLI。请先安装 Codex CLI。",
  "not-authenticated": "Codex CLI 尚未登录。请先在终端运行 codex login。",
  "unsupported-installation":
    "检测到的 Codex CLI 安装无法安全验证。请使用官方 npm、install.sh、Homebrew cask 或签名发行版。",
  "move-to-applications":
    "请先把 Local Context Forge 拖入“应用程序 (Applications)”文件夹，重新打开后再试。",
  "source-debug": "源码调试版本不会写入持久 Codex 配置，请使用已打包应用。",
  "bundle-invalid": "应用内的 MCP companion 无法安全验证，请重新安装应用。",
  "name-conflict":
    "Codex 中已有同名的自定义 MCP server。为避免覆盖，本应用没有修改它。",
  timeout: "Codex CLI 响应超时。请确认没有交互提示占用终端后重试。",
  "invalid-response": "Codex CLI 返回了无法验证的结果，配置未被视为成功。",
  unavailable: "暂时无法完成 MCP 设置。请确认 Codex CLI 可运行后重试。"
};

function errorMessage(error: unknown): string {
  const code =
    error &&
    typeof error === "object" &&
    "code" in error &&
    typeof error.code === "string"
      ? error.code
      : "unavailable";
  return (
    ERROR_MESSAGES[code as DesktopMcpSetupErrorCode] ??
    ERROR_MESSAGES.unavailable
  );
}

function statusCopy(status: DesktopMcpSetupStatus): {
  title: string;
  detail: string;
  tone: "ready" | "warning" | "muted";
} {
  if (status.installState === "move-to-applications") {
    return {
      title: "先移动应用",
      detail:
        "请把 Local Context Forge 拖入“应用程序 (Applications)”文件夹，再重新打开并重试。本应用不会自行移动。",
      tone: "warning"
    };
  }
  if (status.installState === "source-debug") {
    return {
      title: "源码调试模式",
      detail: "源码调试版本不会写入持久 Codex 配置；请使用已打包应用。",
      tone: "muted"
    };
  }
  if (status.installState === "bundle-invalid") {
    return {
      title: "应用组件无法验证",
      detail: "MCP companion 或随附 Node 运行时缺失或不安全，请重新安装应用。",
      tone: "warning"
    };
  }
  if (status.codexState === "not-installed") {
    return {
      title: "未找到 Codex CLI",
      detail: "请先安装官方 Codex CLI，再回到这里刷新。",
      tone: "warning"
    };
  }
  if (status.codexState === "not-authenticated") {
    return {
      title: "Codex CLI 尚未登录",
      detail: "请先在终端运行 codex login，登录完成后刷新。",
      tone: "warning"
    };
  }
  if (status.codexState === "unsupported-installation") {
    return {
      title: "Codex CLI 安装不受支持",
      detail:
        "仅自动配置可验证的官方 npm、install.sh、Homebrew cask，或安装在 /usr/local/bin/codex 的签名 arm64 发行版。",
      tone: "warning"
    };
  }
  if (status.codexState === "unavailable") {
    return {
      title: "Codex CLI 暂时不可用",
      detail: "请确认 Codex CLI 可以正常启动，再刷新状态。",
      tone: "warning"
    };
  }
  if (status.configurationState === "configured") {
    return {
      title: "已连接 Codex",
      detail: status.restartRequired
        ? "配置已更新。请重启 Codex（或新建 CLI 会话），以加载本地文档工具。"
        : "Codex 已登记本地文档工具；重启 Codex或新建 CLI 会话即可使用。",
      tone: "ready"
    };
  }
  if (status.configurationState === "needs-reconnect") {
    return {
      title: "需要重新连接",
      detail:
        "检测到应用曾移动或连接仍指向旧位置。点击“重新连接 Codex”即可替换旧记录。",
      tone: "warning"
    };
  }
  if (status.configurationState === "name-conflict") {
    return {
      title: "同名配置冲突",
      detail:
        "Codex 中已有同名的自定义 MCP server。为避免覆盖，请先在 Codex 中自行处理该记录。",
      tone: "warning"
    };
  }
  if (status.configurationState === "not-configured") {
    return {
      title: "尚未连接 Codex",
      detail: "点击一次即可登记只读的本地文档工具。",
      tone: "muted"
    };
  }
  return {
    title: "无法确认连接状态",
    detail: "请确认 Codex CLI 已安装并可运行，然后刷新。",
    tone: "warning"
  };
}

export function McpOnboarding() {
  const [status, setStatus] = useState<DesktopMcpSetupStatus>();
  const [operation, setOperation] = useState<Operation>();
  const [error, setError] = useState("");
  const requestSequence = useRef(0);

  const run = useCallback(
    async (nextOperation: Operation) => {
      const requestId = ++requestSequence.current;
      setOperation(nextOperation);
      setError("");
      try {
        const bridge = desktopMcpBridge();
        if (!bridge) {
          throw new Error("Desktop MCP bridge unavailable");
        }
        const next =
          nextOperation === "configure"
            ? await bridge.configure()
            : nextOperation === "clear"
              ? await bridge.clear()
              : await bridge.status();
        if (requestSequence.current === requestId) {
          setStatus(next);
        }
      } catch (requestError) {
        if (requestSequence.current === requestId) {
          setError(errorMessage(requestError));
        }
      } finally {
        if (requestSequence.current === requestId) {
          setOperation(undefined);
        }
      }
    },
    []
  );

  useEffect(() => {
    void run("refresh");
    return () => {
      requestSequence.current += 1;
    };
  }, [run]);

  const copy = status ? statusCopy(status) : undefined;
  const busy = operation !== undefined;

  return (
    <section className="panel settings-section mcp-onboarding">
      <header className="panel__header">
        <div>
          <span className="step-badge">2</span>
          <h2>在 Codex 中使用本地文档</h2>
          <p>安全登记随应用提供的只读 MCP companion。</p>
        </div>
      </header>

      <div className="mcp-onboarding__body">
        <div
          className={`mcp-onboarding__status mcp-onboarding__status--${
            copy?.tone ?? "muted"
          }`}
          aria-live="polite"
          aria-busy={operation === "refresh"}
        >
          <span>
            <Icon
              name={copy?.tone === "ready" ? "check" : "terminal"}
              size={19}
            />
          </span>
          <div>
            <strong>
              {copy?.title ??
                (operation === "refresh" ? "正在检查 Codex…" : "等待检查")}
            </strong>
            <small>{copy?.detail ?? "正在读取安全的连接状态。"}</small>
          </div>
        </div>

        {error && (
          <div className="mcp-onboarding__error" role="alert">
            <Icon name="lint" size={17} />
            <span>{error}</span>
          </div>
        )}

        <div className="button-row">
          {status?.canConfigure && (
            <button
              className="button button--primary"
              disabled={busy}
              onClick={() => void run("configure")}
            >
              {operation === "configure"
                ? "正在连接…"
                : status.configurationState === "needs-reconnect"
                  ? "重新连接 Codex"
                  : "连接 Codex"}
            </button>
          )}
          <button
            className="button button--small"
            disabled={busy}
            onClick={() => void run("refresh")}
          >
            <Icon name="refresh" size={14} />
            {operation === "refresh" ? "检查中…" : "刷新状态"}
          </button>
          {status?.canClear && (
            <button
              className="button button--small"
              disabled={busy}
              onClick={() => void run("clear")}
            >
              {operation === "clear" ? "正在清除…" : "清除本应用的连接"}
            </button>
          )}
        </div>

        <aside className="mcp-onboarding__cursor">
          <strong>Cursor：仅手动后备</strong>
          <p>
            当前版本不会自动配置 Cursor，也不会静默运行 Cursor CLI。需要时请打开
            Cursor 的 MCP 设置，按 Cursor 官方文档手动添加本地 stdio server。
          </p>
        </aside>
      </div>
    </section>
  );
}
