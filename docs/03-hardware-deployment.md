# M4 Pro 24 GB + 可选 Windows 32 GB / RTX 4060 部署

## 先给结论

对于日常使用最多的 M4 Pro 24 GB MacBook，Electron all-in-one 是合理目标：控制面、SQLite、
Wiki、QMD、MCP、Python sidecar 和 Node worker 都在一台 Mac 上运行，生成阶段调用该用户已经
登录的 Codex CLI。24 GB 统一内存足以采用小型本地 embedding 和单任务队列，不需要让
Windows 电脑常驻。

不过，只有在公开 Release 出现**经过审查的 DMG**，并完成干净用户安装与真实 provider
验证后，Electron 才能成为推荐安装方式。目前这些物理门禁仍是 `not-run`。现在必须稳定运行
时，可继续使用 legacy Docker 路径。

## 推荐分工

| 设备 | Electron 桌面版职责 | legacy 可选职责 |
| --- | --- | --- |
| M4 Pro MacBook · 24 GB | Electron Main、Web UI、Python sidecar、QMD、SQLite、Wiki、MCP、Codex/Cursor CLI | Docker/Web 控制面 |
| Windows · 32 GB + RTX 4060 | 当前没有桌面远程 worker 能力 | 可运行 Ollama，为 legacy Docker/Web 提供局域网生成 |

桌面应用不会把源码自动发送到 Windows，也没有面向远程 Ollama 的桌面设置入口。若使用
Windows GPU，必须明确选择 legacy 拓扑，并按现有安全文档限制局域网访问。

## M4 Pro 24 GB 的默认配置

### 生成

- 默认：Codex CLI；
- 任务并发：固定为 1；
- Cursor：默认关闭，只能由用户在“设置”中明确同意；
- Codex 已进入执行阶段后不做 Cursor fallback；
- 每次生成只得到有界证据和结构化输出，不能直接发布 Wiki。

这种设置比并行跑多个 Agent 更适合 24 GB 机器：队列可追踪，也避免本地 embedding 与
生成任务同时出现多个峰值。

### Embedding

默认建议：

```text
hf:ggml-org/embeddinggemma-300M-GGUF/embeddinggemma-300M-Q8_0.gguf
```

备选：

```text
hf:Qwen/Qwen3-Embedding-0.6B-GGUF/Qwen3-Embedding-0.6B-Q8_0.gguf
```

实际可选项由应用 API 返回，UI 会显示 curated preset。高级用户只能填写符合
`hf:org/repo/file.gguf` 形式、属于 EmbeddingGemma 或 Qwen3-Embedding 家族的 GGUF 标识；
HTTP URL 和本地任意路径会被拒绝。

模型不会随 DMG 预装。第一次明确发起 embedding rebuild 时，QMD 才可能下载所选模型。下载、
native embedding 和 hybrid 检索尚需物理 Apple Silicon 门禁；模型未就绪时，指定 library
且 QMD broker 健康的 desktop 查询使用 BM25，broker/revision 失败或全局查询使用 Python
lexical，不会混用旧向量。

### 磁盘与电源

建议预留至少 10 GiB 空闲空间，较大的 monorepo、多个不可变快照和模型缓存需要更多。长时间
首次采集或重建时：

- 连接电源；
- 暂停大型本地模型、虚拟机和视频导出；
- 不要同时启动 legacy Docker writer 和 Electron；
- 不要在任务 `running` 时强制结束应用。

精确占用取决于源码快照、Wiki 历史、QMD 索引和所选 GGUF，文档不提供虚假的固定容量承诺。

## Electron 进程与资源边界

```text
React renderer
    │ typed IPC
    ▼
Electron Main
    ├── private UDS ── Python 3.13.14 sidecar
    ├── private broker ── Node 22.23.2 / QMD 2.5.3 worker
    ├── supervised Codex/Cursor CLI
    └── read-only MCP companion bridge + scoped ownership ledger
```

正式应用目标是不依赖目标机安装 Docker、Homebrew、Python、Node、Git、QMD 或 ctags。
Codex CLI 不属于内部 runtime：Wiki 生成默认使用用户自己的已登录 CLI；没有可用 Codex 时，
采集会明确失败，除非用户事先允许符合条件的 Cursor fallback。

## 只用一台 M4 Mac

这是桌面版的目标拓扑。安装经过审查的 DMG 后：

1. 把应用拖到 `/Applications`；
2. 在终端完成 `codex login`；
3. 打开应用并添加本地或公开 GitHub 仓库；
4. 在“任务”观察单并发队列；
5. 在“审核”批准页面；
6. 在“设置”选择 embedding 并重建；
7. 点击“连接 Codex”登记 MCP。

完整步骤见 [快速开始](04-quickstart.md) 与
[Electron 桌面版完整指南](16-electron-desktop-guide.md)。

## Windows/4060 什么时候有价值

只有在以下场景才建议启用：

- 你仍运行 legacy Docker/Web；
- 希望不用 Codex/Cursor，而是显式使用局域网 Ollama；
- 能把 Windows 防火墙限制到 Mac 的固定私网 IP；
- 接受源码证据会从 Mac 发送到 Windows 上的模型服务。

旧拓扑的准备命令仍是：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\windows-ollama-setup.ps1 `
  -MacAddress 192.168.1.20 `
  -InstallOllama `
  -RestartOllama
```

把地址替换为 Mac 的固定私网地址。随后只在 legacy `.env` 中配置 Windows Ollama。不要把
`11434` 暴露到公网，也不要误以为这些设置会被 Electron 桌面版读取。

## 两条部署路径不要混用

| 项目 | Electron | legacy Docker/Web |
| --- | --- | --- |
| 安装入口 | 经过审查的 arm64 DMG | `./install.sh` 或 `install.command` |
| 数据根 | `~/Library/Application Support/Local Context Forge/` | checkout 的 `data/` 或配置的 bind mount |
| 本地模型缓存 | `~/Library/Caches/Local Context Forge/` | Compose/native QMD 配置 |
| 生成工具 | Codex；显式 Cursor fallback | Codex/Cursor host runner、mock 或 Ollama |
| MCP | app 内 stdio companion | streamable HTTP gateway |
| Windows Ollama | 未实现 | 可选 |

两套 writer 不能同时指向同一份数据。桌面版的 legacy 数据迁移门禁仍未运行，不要手工把
`data/` 覆盖到 Application Support。需要回退时，保留原 legacy checkout、备份和容器配置，
分别运行。

## 性能调优顺序

1. 先用 EmbeddingGemma 300M Q8 和固定单并发完成真实查询集；
2. 观察 lexical fallback 是否已经满足 API/符号检索；
3. 再试 Qwen3-Embedding 0.6B Q8，并用同一查询集比较；
4. 只有明确需要本地生成时才启用 Windows Ollama legacy 节点；
5. 不通过提高并发掩盖慢任务；先检查仓库规模、模型状态和任务阶段。

LCF 的主要瓶颈通常是首次源码编译、Codex 生成、人工审核或首次模型准备，而不是 Web UI。
