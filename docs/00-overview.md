# Local Context Forge：本地 Context7 平替

Local Context Forge（LCF）把代码仓库编译成一套**可审核、可版本化、可检索、可通过 MCP
消费**的 API Wiki。它不仅建立代码向量索引，还保存页面、结构化元数据、源码引用、审核状态
和 Git 历史。

```text
不可变源码快照
    ↓
确定性事实与源码范围
    ↓
Codex CLI 生成知识提案
    ↓
schema / source SHA / 路径 / 行号验证
    ↓
人工批准或拒绝
    ↓
Git-backed Wiki + SQLite 物化页
    ↓
QMD hybrid 或 lexical 查询
    ↓
resolve-library-id / query-docs
```

## 它解决什么问题

普通代码 RAG 往往只保存临时切块，难以回答“这个结论来自哪个提交、哪几行、是否经过
审核”。LCF 把生成结果先当作提案：

- 每次采集绑定确定的 ref、完整 source SHA 和新的不可变版本；
- 页面必须携带实际提供给生成器的源码引用；
- 提案不会自动进入查询，必须在 Web 界面批准；
- 同一版本全部批准后才激活，拒绝或部分成功版本不会冒充正式知识；
- 发布后的 Wiki 可 diff、可 lint，也能被 Context7 风格 MCP 工具查询。

## 桌面版的使用体验

目标用户只需要一个 macOS 应用：

1. 在“仓库”中粘贴公开 GitHub HTTPS 地址，或用系统选择器授权本地仓库；
2. 选择分支、标签或提交并提交采集；
3. 在“任务”中查看持久 FIFO 队列、进度、取消、失败和显式重试；
4. 在“审核”中逐页检查 Markdown 与源码引用，再批准或拒绝；
5. 在“查询”中检索已发布知识；
6. 在“设置”中选择 embedding 模型、保存并发起全量重建；
7. 点击“连接 Codex”，把只读的两个 MCP 工具登记到本机 Codex CLI。

Codex CLI 是桌面版唯一默认生成工具。只有用户在设置中明确同意，而且任务开始前确认 Codex
未安装或未登录时，才允许选择已登录的 Cursor CLI。Codex 一旦提交执行，后续超时或失败不会
再切换到 Cursor，避免重复消耗额度和产生冲突结果。

## M4 Pro 24 GB 推荐配置

| 项目 | 默认选择 |
| --- | --- |
| 桌面平台 | macOS Apple Silicon |
| 生成工具 | 已登录的 Codex CLI |
| Cursor | 仅显式同意的 preflight fallback |
| Embedding | EmbeddingGemma 300M Q8 |
| 备选 embedding | Qwen3-Embedding 0.6B Q8 |
| 任务并发 | 固定为 1 |
| 查询降级 | embedding 未就绪时使用 lexical |

Embedding 是全局 profile。更换模型或发布新语料会使旧向量变为 stale；“保存并重建全部”
会创建一个队列任务。索引重建只处理已发布 Wiki，不调用 Codex/Cursor，也不会消耗生成额度。

Windows 32 GB + RTX 4060 仍可作为 legacy Docker/Ollama 部署的可选生成节点，但当前 Electron
客户端没有实现远程 Windows worker；不要把两条拓扑混为一谈。详见
[硬件与部署](03-hardware-deployment.md)。

## 当前交付状态

桌面源码已经包含 Electron Main/preload/renderer、Python sidecar、Node/QMD worker、
本地仓库授权、provider 监督、MCP companion、embedding 重建和受保护 Release 工作流。
这不等于已有可推荐安装包：

| 门禁 | 当前状态 |
| --- | --- |
| 源码单元、合同与构建检查 | 已有自动化证据 |
| 公开仓库中的正式 DMG | 尚无经过审查的 Release 资产 |
| 干净 macOS 用户安装 | `not-run` |
| 打包应用中的真实 Codex 采集 | `not-run` |
| 物理 Apple Silicon 模型下载/重建 | `not-run` |
| 0.0.1 → 0.0.2 物理更新 | `not-run` |

因此：

- **普通用户**：等公开 Release 同时提供经过审查的 DMG、`SHA256SUMS`、
  `release-manifest.json` 和签名更新元数据后，再按
  [桌面版完整指南](16-electron-desktop-guide.md)安装。
- **开发者**：可以运行源码模式验证，但它不能证明 DMG、签名、clean-user 或更新门禁。
- **需要现在稳定运行**：继续使用 legacy Docker/Web 路径；它不会被桌面开发静默删除。

## 安全边界

- Renderer 没有 Node、shell、原始文件路径、启动令牌、socket、更新器或任意进程能力；
- Electron Main 负责系统目录选择、进程生命周期、私有 UDS、provider 和更新校验；
- 本地仓库选择只向页面返回显示名和单次授权 ID，完整路径不进入 renderer；
- MCP 只有 `resolve-library-id` 与 `query-docs`，没有采集、审核、发布或设置权限；
- 仓库内容和模型输出都视为不可信数据，人工审核仍是事实正确性的必要步骤；
- 产品当前是本机单用户应用，不是带认证、ACL、TLS 的共享服务。

自签名发行版不使用 Apple Developer ID、不 notarize，也不启用 hardened runtime。它不应被
描述为“Apple 已验证”。首次打开应使用 Finder 的“打开”或系统设置中的“仍要打开”，不能
通过关闭 Gatekeeper、移除 quarantine 或使用 `sudo` 绕过系统保护。

## 从这里继续

- [安装与第一次查询](04-quickstart.md)
- [Electron 桌面版完整指南](16-electron-desktop-guide.md)
- [架构](01-architecture.md)
- [API 与 MCP](06-api-and-mcp.md)
- [安全与威胁模型](10-security.md)
- [开发与验证状态](development/README.md)
