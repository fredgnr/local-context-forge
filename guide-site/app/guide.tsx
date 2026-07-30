"use client";

import { useState } from "react";

type CodeBlockProps = {
  label: string;
  code: string;
  language?: string;
};

function CodeBlock({ label, code, language = "shell" }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
    } catch {
      const area = document.createElement("textarea");
      area.value = code;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  return (
    <div className="code-block">
      <div className="code-toolbar">
        <span>{label}</span>
        <button type="button" onClick={copy} aria-label={`复制${label}`}>
          {copied ? "已复制 ✓" : "复制"}
        </button>
      </div>
      <pre>
        <code data-language={language}>{code}</code>
      </pre>
      <span className="sr-only" aria-live="polite">
        {copied ? `${label}已复制` : ""}
      </span>
    </div>
  );
}

const install = `unzip local-context-forge-complete.zip
cd local-context-forge
./install.sh`;

const daily = `./scripts/lcf status
./scripts/lcf doctor
./scripts/lcf logs

# 停止 / 再启动（数据不会删除）
./scripts/lcf stop
./scripts/lcf start`;

const advanced = `# 指定已就绪的容器运行时
./install.sh --runtime docker-desktop
./install.sh --runtime colima

# 暂时没有 Codex/Cursor 时，先用确定性 mock 验证流程
./install.sh --provider mock --no-open

# 查看全部高级参数
./scripts/lcf install --help`;

const cliChecks = `codex login status
cursor-agent status

# Local Context Forge 的综合检查
./scripts/lcf doctor`;

const mcp = `codex mcp add local-context-forge \\
  --url http://127.0.0.1:8001/mcp
codex mcp list`;

const backup = `./scripts/backup.sh

# 默认卸载只移除常驻服务，保留 data / imports / backups
./scripts/lcf uninstall`;

const modelUri =
  "hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf";

const stages = [
  ["01", "预检", "识别 Apple Silicon、磁盘、端口、Docker Desktop / Colima 和 CLI 登录状态。"],
  ["02", "本机 Runner", "有可用 CLI 时安装用户级 LaunchAgent；登录凭据不进入容器。无 CLI 的首次安装进入 mock 演示。"],
  ["03", "核心服务", "启动 API、SQLite、QMD、MCP 与 Web；默认只监听 127.0.0.1。"],
  ["04", "验收", "等待健康检查；CLI 模式检查 Runner 心跳，最后打开 Web 引导页。"],
];

const workflow = [
  ["提交仓库", "输入 HTTPS Git 地址或选择 imports 中的本地仓库，确认 ref 与版本标签。"],
  ["进入队列", "所有采集与重建任务持久化排队；M4 Pro 默认单并发，避免内存和额度突刺。"],
  ["生成提案", "默认复用已登录 Codex CLI；仅在预检不可用时，按配置使用 Cursor CLI。"],
  ["人工审核", "逐页查看 Markdown、源码路径、行号与 SHA；批准后才进入可查询 Wiki。"],
  ["本地查询", "Web 与 Context7-compatible MCP 读取已激活版本，不把未审核草案混入结果。"],
];

function StatusDot({ tone = "ok" }: { tone?: "ok" | "wait" | "muted" }) {
  return <i className={`status-dot status-dot--${tone}`} aria-hidden="true" />;
}

function ConsolePreview() {
  return (
    <div className="console-preview" aria-label="Web 控制台界面示意">
      <div className="preview-chrome">
        <span />
        <span />
        <span />
        <b>localhost:8080</b>
      </div>
      <div className="preview-body">
        <aside>
          <div className="preview-logo">LCF</div>
          {["首页", "仓库", "任务", "审核", "查询", "设置"].map((item, index) => (
            <div className={index === 0 ? "active" : ""} key={item}>
              <span />
              {item}
            </div>
          ))}
        </aside>
        <div className="preview-main">
          <div className="preview-heading">
            <div>
              <small>本地系统控制面</small>
              <h3>把代码仓库变成可查询的 API Wiki</h3>
            </div>
            <button type="button">＋ 添加仓库</button>
          </div>
          <div className="preview-checks">
            <article>
              <StatusDot />
              <span>
                <b>Codex CLI</b>
                <small>已登录 · 默认生成器</small>
              </span>
              <em>就绪</em>
            </article>
            <article>
              <StatusDot />
              <span>
                <b>Embedding</b>
                <small>EmbeddingGemma 300M · Q8</small>
              </span>
              <em>就绪</em>
            </article>
            <article>
              <StatusDot tone="wait" />
              <span>
                <b>待审核</b>
                <small>acme/widget · 12 个页面</small>
              </span>
              <em>查看</em>
            </article>
          </div>
          <section className="preview-queue">
            <div>
              <h4>任务队列</h4>
              <small>FIFO · 并发 1</small>
            </div>
            <div className="queue-row">
              <span className="queue-index">01</span>
              <span>
                <b>acme/widget</b>
                <small>正在提取符号与证据</small>
              </span>
              <div className="progress">
                <i />
              </div>
              <em>42%</em>
            </div>
            <div className="queue-row">
              <span className="queue-index">02</span>
              <span>
                <b>openapi/sdk</b>
                <small>等待前一个任务完成</small>
              </span>
              <div className="progress muted">
                <i />
              </div>
              <em>排队中</em>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

export default function Guide() {
  return (
    <main id="top">
      <header className="topbar">
        <a className="brand" href="#top" aria-label="Local Context Forge 首页">
          <span className="brand-symbol" aria-hidden="true">
            LC
          </span>
          <span>
            Local Context Forge
            <small>ALL-IN-ONE · M4 PRO</small>
          </span>
        </a>
        <nav aria-label="页面导航">
          <a href="#architecture">架构</a>
          <a href="#install">部署</a>
          <a href="#workflow">使用</a>
          <a href="#models">模型</a>
          <a href="#advanced">高级</a>
        </nav>
        <a className="nav-action" href="#download">
          下载系统
        </a>
      </header>

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">
            LOCAL-FIRST DOCUMENTATION COMPILER
          </p>
          <h1>
            一个脚本，
            <br />
            把代码库变成
            <br />
            <span>可审核的 API Wiki。</span>
          </h1>
          <p className="hero-lede">
            为 M4 Pro · 24 GB MacBook 调整的本地 Context7 平替。仓库提交、FIFO
            排队、文档生成、人工审核、Embedding 切换、重建与查询都在一个 Web
            控制台完成；默认复用你已经登录的 Codex CLI。
          </p>
          <div className="hero-badges" aria-label="核心特性">
            <span><StatusDot />默认仅本机访问</span>
            <span><StatusDot />Codex 登录不进容器</span>
            <span><StatusDot />失败不覆盖旧索引</span>
          </div>
          <CodeBlock label="唯一必需命令" code={install} />
          <p className="microcopy">
            不想输入命令也可以：解压后双击 <code>install.command</code>。首次运行会显示每一步检查；
            不会自动安装或登录 Codex/Cursor，也不会删除已有数据。
          </p>
        </div>
        <ConsolePreview />
      </section>

      <section className="section intro-strip">
        <div>
          <small>DEFAULT HARDWARE PROFILE</small>
          <strong>M4 Pro · 24 GB</strong>
          <span>队列并发 1 · 容器核心 + 本机 CLI Runner</span>
        </div>
        <div>
          <small>WIKI GENERATION</small>
          <strong>Codex CLI → Cursor CLI</strong>
          <span>仅预检不可用时 fallback，不对失败请求重复消费额度</span>
        </div>
        <div>
          <small>LOCAL RETRIEVAL</small>
          <strong>QMD + SQLite</strong>
          <span>EmbeddingGemma 300M Q8 · lexical 自动兜底</span>
        </div>
      </section>

      <section className="section architecture" id="architecture">
        <div className="section-heading">
          <p className="eyebrow">ARCHITECTURE</p>
          <h2>容器负责服务，本机 Runner 负责登录态。</h2>
          <p>
            这是 all-in-one 的关键边界：不把 <code>~/.codex</code>、
            Cursor 凭据或 Docker socket 挂进容器。两侧通过只含有界证据和固定任务类型的
            本地文件队列通信。
          </p>
        </div>
        <div className="architecture-map" role="img" aria-label="Local Context Forge 架构图">
          <article className="map-column">
            <span className="map-label">BROWSER · 127.0.0.1</span>
            <div className="map-card accent-card">
              <small>CONTROL PLANE</small>
              <h3>Web Console</h3>
              <p>提交 · 排队 · 审核 · 查询 · 设置</p>
            </div>
          </article>
          <div className="map-arrow" aria-hidden="true">→</div>
          <article className="map-column wide">
            <span className="map-label">DOCKER / COLIMA</span>
            <div className="map-stack">
              <div className="map-card">
                <small>CORE API</small>
                <h3>FastAPI + Durable Queue</h3>
                <p>SQLite 状态 · 不可变快照 · 事实提取</p>
              </div>
              <div className="map-card split-card">
                <span><b>QMD</b><small>BM25 / vectors</small></span>
                <span><b>MCP</b><small>Context7 tools</small></span>
              </div>
              <div className="spool-card">
                <span>inbox</span><i>→</i><span>working</span><i>→</i><span>outbox</span>
              </div>
            </div>
          </article>
          <div className="map-arrow" aria-hidden="true">→</div>
          <article className="map-column">
            <span className="map-label">MACOS USER SESSION</span>
            <div className="map-card host-card">
              <small>HOST RUNNER</small>
              <h3>Codex CLI</h3>
              <p>已登录 · ephemeral · read-only</p>
              <hr />
              <h3>Cursor CLI</h3>
              <p>可选 fallback · 不使用 --force</p>
            </div>
          </article>
        </div>
        <div className="boundary-note">
          <b>诚实的安全边界</b>
          <p>
            CLI 仍以当前 macOS 用户身份运行，能访问该用户有权读取的文件；fresh temp 与
            read-only 是风险缩小措施，不是机密隔离。系统定位为受信任的单用户 localhost，
            不是公开多租户服务。
          </p>
        </div>
      </section>

      <section className="section install-section" id="install">
        <div className="section-heading split-heading">
          <div>
            <p className="eyebrow">ONE-SCRIPT INSTALL</p>
            <h2>部署过程可见，也可重复运行。</h2>
          </div>
          <p>
            脚本保留已经存在的配置和数据。失败时只停止本次新启动的服务，不执行
            <code>down -v</code>，也不会替你修改登录凭据。
          </p>
        </div>
        <div className="stage-grid">
          {stages.map(([index, title, detail]) => (
            <article key={index}>
              <span>{index}</span>
              <h3>{title}</h3>
              <p>{detail}</p>
            </article>
          ))}
        </div>
        <div className="two-column">
          <div>
            <h3>部署前只需准备</h3>
            <ul className="check-list">
              <li>macOS Apple Silicon；推荐 20 GB 以上可用磁盘</li>
              <li>Docker Desktop 或 Colima 已安装并可启动</li>
              <li>Git；Python 3 缺失时，有 Homebrew 就会由安装器补齐</li>
              <li>正式生成 Wiki 推荐先完成 <code>codex login</code>；Cursor 仅作备用</li>
            </ul>
            <p className="microcopy">
              图形化路径：解压 ZIP → 双击 <code>install.command</code> → 等待浏览器自动打开。
              若首次没有已登录 CLI，安装器会明确进入 mock 演示；之后登录 Codex 并重新运行安装器即可。
            </p>
          </div>
          <CodeBlock label="部署后常用命令" code={daily} />
        </div>
      </section>

      <section className="section workflow-section" id="workflow">
        <div className="section-heading">
          <p className="eyebrow">PRODUCT WORKFLOW</p>
          <h2>从一个 Git 地址，到可查询知识。</h2>
          <p>
            Web 里的“重新索引”与“重新采集”是两个不同动作：前者只重建检索，不调用
            LLM；后者创建新的不可变源码版本并重新生成 Wiki，会消费 CLI 用量。
          </p>
        </div>
        <div className="workflow-list">
          {workflow.map(([title, detail], index) => (
            <article key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <div>
                <h3>{title}</h3>
                <p>{detail}</p>
              </div>
              {index < workflow.length - 1 ? <i aria-hidden="true">↓</i> : null}
            </article>
          ))}
        </div>
        <div className="review-visual">
          <div className="review-list">
            <span className="map-label">REVIEW BATCH · V1.4.0</span>
            {["Overview", "Client API", "Authentication", "Error handling"].map(
              (title, index) => (
                <div className={index === 1 ? "selected" : ""} key={title}>
                  <StatusDot tone={index < 2 ? "ok" : "wait"} />
                  <span><b>{title}</b><small>docs/{title.toLowerCase().replace(" ", "-")}.md</small></span>
                  <em>{index < 2 ? "已核对" : "待审核"}</em>
                </div>
              ),
            )}
          </div>
          <article className="review-document">
            <span className="map-label">SOURCE-BACKED PROPOSAL</span>
            <h3>Client API</h3>
            <p className="doc-lede">创建客户端、配置请求超时并处理传输错误。</p>
            <div className="doc-code">
              <span>const client = new Client({"{"}</span>
              <span>&nbsp;&nbsp;timeout: 5_000,</span>
              <span>{"}"});</span>
            </div>
            <h4>证据</h4>
            <div className="source-chip">src/client.ts:18–42 · a81d3f2</div>
            <div className="source-chip">examples/basic.ts:7–16 · a81d3f2</div>
            <div className="review-actions">
              <button type="button" className="secondary-button">要求修改</button>
              <button type="button" className="primary-button">批准页面</button>
            </div>
          </article>
        </div>
      </section>

      <section className="section model-section" id="models">
        <div className="section-heading split-heading">
          <div>
            <p className="eyebrow">MODEL CONTROL</p>
            <h2>模型可以换，旧索引不会冒险覆盖。</h2>
          </div>
          <p>
            模型标识先做安全校验，再创建持久化全局重建任务。失败时保留 Wiki/BM25 并
            使用 lexical fallback；只有目标模型与 corpus revision 都匹配才切换 active profile。
          </p>
        </div>
        <div className="model-layout">
          <article className="model-card recommended">
            <div>
              <span className="tag">M4 PRO 推荐</span>
              <small>当前模型</small>
            </div>
            <h3>EmbeddingGemma 300M · Q8</h3>
            <code>{modelUri}</code>
            <ul>
              <li><StatusDot />24 GB 设备有充足余量</li>
              <li><StatusDot />代码检索无需中文专项兼容</li>
              <li><StatusDot />QMD 本地 GGUF 路径</li>
            </ul>
          </article>
          <div className="model-steps">
            <article><span>1</span><b>校验标识</b><small>curated preset 或安全的 hf: GGUF</small></article>
            <article><span>2</span><b>进入队列</b><small>注册完整已发布 corpus</small></article>
            <article><span>3</span><b>构建向量</b><small>按需下载、update、embed -f</small></article>
            <article><span>4</span><b>原子切换</b><small>竞态或失败则保持 lexical</small></article>
          </div>
        </div>
        <div className="boundary-note">
          <b>全局向量边界</b>
          <p>
            QMD 使用一个全局 embedding profile；从某个仓库点击“重建”只是指定任务入口，
            不会创建混用不同模型的局部向量空间。索引重建不调用 Codex/Cursor。
          </p>
          <p>
            首次 hybrid 查询还会按需缓存约 640 MB 的重排模型和约 1.1 GB 的查询扩展模型；
            第一次查询会明显更慢并需要联网，后续复用本地缓存。
          </p>
        </div>
        <div className="provider-table">
          <div className="table-row table-head">
            <span>生成器</span><span>默认用途</span><span>认证</span><span>自动 fallback</span>
          </div>
          <div className="table-row">
            <span><b>Codex CLI</b><small>默认</small></span>
            <span>生成 typed Wiki 提案</span>
            <span>复用本机 ChatGPT / API key 登录</span>
            <span>—</span>
          </div>
          <div className="table-row">
            <span><b>Cursor CLI</b><small>备用</small></span>
            <span>Codex 预检不可用时</span>
            <span>复用本机 Cursor 登录</span>
            <span>仅 binary/auth 预检失败</span>
          </div>
          <div className="table-row">
            <span><b>Mock</b><small>诊断</small></span>
            <span>离线验证完整流水线</span>
            <span>不需要</span>
            <span>永不自动启用</span>
          </div>
        </div>
      </section>

      <section className="section advanced-section" id="advanced">
        <div className="section-heading">
          <p className="eyebrow">BASIC FIRST, POWER WHEN NEEDED</p>
          <h2>新手看到下一步，资深用户拿到全部开关。</h2>
        </div>
        <div className="command-grid">
          <CodeBlock label="高级部署参数" code={advanced} />
          <CodeBlock label="CLI 登录检查" code={cliChecks} />
          <CodeBlock label="接入 Codex MCP" code={mcp} />
          <CodeBlock label="备份与保留数据卸载" code={backup} />
        </div>
        <div className="advanced-grid">
          <article>
            <h3>基础模式默认值</h3>
            <ul>
              <li>绑定 127.0.0.1</li>
              <li>单 worker / FIFO</li>
              <li>Codex CLI 优先</li>
              <li>EmbeddingGemma 300M Q8</li>
              <li>人工审核后激活</li>
            </ul>
          </article>
          <article>
            <h3>高级设置可调整</h3>
            <ul>
              <li>Docker Desktop / Colima context</li>
              <li>CLI 模型与 provider 顺序</li>
              <li>Embedding URI 与 rebuild scope</li>
              <li>任务并发、超时、证据预算</li>
              <li>远端 Git allowlist 与端口</li>
            </ul>
          </article>
          <article>
            <h3>明确不做的事</h3>
            <ul>
              <li>不挂载个人认证目录</li>
              <li>不把 Docker socket 给 Web</li>
              <li>不公开监听所有网卡</li>
              <li>不自动重复失败的付费生成</li>
              <li>不把未审核页面交给 MCP</li>
            </ul>
          </article>
        </div>
      </section>

      <section className="section troubleshooting">
        <div className="section-heading">
          <p className="eyebrow">TROUBLESHOOTING</p>
          <h2>先跑 doctor，再看明确的修复动作。</h2>
        </div>
        <div className="faq-grid">
          <details>
            <summary>双击 install.command 没有运行怎么办？</summary>
            <p>
              先在 Finder 中右键它并选择“打开”。若企业安全策略仍阻止脚本，就复制页面顶部的
              三行命令到 Terminal；两条路径调用的是同一个安装器。
            </p>
          </details>
          <details>
            <summary>Codex 显示“未登录”怎么办？</summary>
            <p>
              在同一个 macOS 用户终端执行 <code>codex login</code>，完成浏览器登录后运行
              <code>codex login status</code>。若此前用 mock 安装，请重新运行
              <code>./install.sh --provider auto</code> 来安装 Host Runner 并同步设置；
              其他情况再执行 <code>./scripts/lcf restart</code>。
            </p>
          </details>
          <details>
            <summary>Docker Desktop 和 Colima 都安装了怎么办？</summary>
            <p>
              安装器不会静默切换 context。先启动你要用的 runtime，再通过
              <code>--runtime docker-desktop</code> 或 <code>--runtime colima</code>明确选择。
            </p>
          </details>
          <details>
            <summary>Embedding 下载或重建失败会影响查询吗？</summary>
            <p>
              不会自动替换当前 active profile。任务失败会保留旧索引；没有向量时查询还会
              回退到确定性 lexical 搜索。
            </p>
          </details>
          <details>
            <summary>为什么任务一直排队？</summary>
            <p>
              M4 Pro 默认并发为 1。打开“任务”查看前一个任务阶段；若 Runner 心跳异常，
              <code>./scripts/lcf doctor</code> 会检查 LaunchAgent 和 CLI 登录。
            </p>
          </details>
          <details>
            <summary>Codex 失败后为什么没有自动改用 Cursor？</summary>
            <p>
              为避免一次任务重复消费两份额度，只有 Codex binary/auth 预检不可用时才 fallback。
              超时、模型错误或输出校验失败需要你在 Web 中明确重试。
            </p>
          </details>
          <details>
            <summary>可以让局域网其他设备访问吗？</summary>
            <p>
              默认不建议。当前产品是受信任的单用户 localhost，未提供多用户认证、TLS 与 ACL。
              高级用户若反向代理，应自行补齐这些控制。
            </p>
          </details>
        </div>
      </section>

      <section className="section download-section" id="download">
        <div>
          <p className="eyebrow">DOWNLOAD</p>
          <h2>完整源码，一包带走。</h2>
          <p>
            包含后端、MCP、Web、Host Runner、Dockerfile、Compose、一键部署脚本、测试和完整说明。
            本次交付不生成 PDF。
          </p>
        </div>
        <div className="download-card">
          <span>LOCAL CONTEXT FORGE</span>
          <h3>All-in-one source package</h3>
          <p>macOS Apple Silicon · Docker Desktop / Colima</p>
          <a href="/downloads/local-context-forge-complete.zip" download>
            下载 ZIP <b aria-hidden="true">↓</b>
          </a>
          <a
            className="checksum-link"
            href="/downloads/local-context-forge-complete.zip.sha256"
            download
          >
            下载 SHA-256
          </a>
        </div>
      </section>

      <footer>
        <div className="brand footer-brand">
          <span className="brand-symbol" aria-hidden="true">LC</span>
          <span>Local Context Forge<small>LOCAL-FIRST API WIKI</small></span>
        </div>
        <p>
          官方参考：
          <a href="https://learn.chatgpt.com/docs/non-interactive-mode">Codex non-interactive mode</a>
          <span>·</span>
          <a href="https://learn.chatgpt.com/docs/auth">Codex authentication</a>
          <span>·</span>
          <a href="https://docs.cursor.com/en/cli/headless">Cursor headless CLI</a>
        </p>
        <a href="#top">回到顶部 ↑</a>
      </footer>
    </main>
  );
}
