# GitHub Actions 与 GHCR

> `vX.Y.Z` 是**统一产品发行事件**，不是“只给容器打标签”。同一个 tag 还会触发
> `.github/workflows/desktop-release.yml` 的受保护 macOS 候选构建。创建 tag 前必须完成
> [桌面发行 runbook](development/desktop-release.md)中的版本同步、Environment、ruleset、
> trust pins 和审批准备；当前 public locks 为 `unprovisioned`，整体仍是
> **source merge GO / release NO-GO**。GHCR SemVer 镜像出现不代表桌面 Draft/Release 已通过。

仓库通过 `.github/workflows/container-images.yml` 构建并托管三个镜像：

```text
ghcr.io/fredgnr/local-context-forge-api
ghcr.io/fredgnr/local-context-forge-mcp
ghcr.io/fredgnr/local-context-forge-web
```

Codex CLI、Cursor CLI、登录缓存和 Host Runner 不进入镜像。Host Runner 仍由 macOS 当前用户
的 LaunchAgent 运行，只通过 `data/runner` 中的有界 JSON spool 与 API 交换数据。

## 触发与标签

| 事件 | 行为 | 标签 |
| --- | --- | --- |
| PR 到 `main` | 双架构构建验证，不登录、不推送 | 无 |
| push 到 `main` | 构建并推送三个镜像 | `main`、`sha-<12位>` |
| push `vX.Y.Z` | 构建并推送版本镜像；同时触发桌面候选流程 | `X.Y.Z`、`X.Y`、`sha-<12位>` |
| 手动运行 | 重建所选 ref | 按 ref 规则 |

每个镜像同时包含 `linux/arm64` 和 `linux/amd64`。M4/Colima 自动选择 arm64，常规
x86_64 Linux/Windows VM 自动选择 amd64。流水线使用独立 cache scope、BuildKit
`mode=max` provenance 和 SPDX SBOM；这些提供来源追踪，不代表依赖已完全可复现。

工作流只授予：

```yaml
permissions:
  contents: read
  packages: write
```

发布使用仓库自动生成的 `GITHUB_TOKEN`，不需要配置 PAT、Codex secret 或 OpenAI key。
第三方 Actions 固定到完整 commit SHA，并由 Dependabot 每周检查更新。

## 首次 `main` 镜像构建

把 workflow 提交到 `main` 会自动启动第一次 `main` 镜像构建与推送；这不是版本 Release。
打开：

```text
https://github.com/fredgnr/local-context-forge/actions
```

选择 **Build and publish container images**，确认 `api`、`mcp`、`web` 三个 matrix job
均成功。随后在 GitHub 个人主页的 **Packages** 中检查三个包。每个包应：

1. 关联到 `fredgnr/local-context-forge`；
2. 在 **Package settings → Manage Actions access** 中允许该仓库写入；
3. 保持 private，除非你明确希望公开镜像层中的应用代码。

工作流会设置 `org.opencontainers.image.source`，正常情况下首次发布即自动关联仓库。

## 登录私有 GHCR

GitHub 网页已登录不代表 Docker CLI 已登录。GitHub Container Registry 本地拉取私有包需要
classic PAT，最低权限为 `read:packages`。不要把 PAT 放在命令参数、仓库、`.env`、
`.lcf/runtime.env`、Compose 文件或容器环境中。

在终端隐藏输入并通过标准输入登录：

```bash
read -s CR_PAT
printf '%s' "$CR_PAT" |
  docker login ghcr.io -u fredgnr --password-stdin
unset CR_PAT
```

Docker Desktop 通常写入 macOS Keychain；Colima 使用当前 Docker CLI 配置的 credential
store。若切换 Docker context 后拉取失败，先检查当前 context：

```bash
docker context show
docker context ls
docker info
```

Colima 未运行时：

```bash
colima start
docker context use colima
docker info
```

## 使用预构建镜像一键部署

在源码 checkout 根目录运行：

```bash
LCF_CONTROL_BIN="$(pwd -P)/scripts/lcf"
lcf_managed() {
  env -i HOME="$HOME" PATH="$PATH" "$LCF_CONTROL_BIN" "$@"
}

lcf_managed install --images ghcr --image-tag main
```

最小环境包装用于清除可能覆盖 Compose project、data、bind、port 或 image 的调用者变量；
实现缺口与高级 allowlist 见[部署总手册](18-deployment-operations.md#22-安装)。

安装器会：

1. 把三个 GHCR 镜像地址写入 mode `600` 的 `.lcf/runtime.env`；
2. 执行 `docker compose pull`，确保可变的 `main` 标签更新；
3. 使用 `docker compose up --no-build` 启动；
4. 等待三个服务健康并执行 smoke/doctor。

任何 Registry token 都不会写入 runtime env。拉取失败时安装器会停止，不会回退为不明确的
本地镜像。

稳定版本建议使用精确标签：

```bash
lcf_managed install --images ghcr --image-tag 0.1.0
```

需要和某个源码提交严格对应时，使用该次流水线生成的 SHA 标签：

```bash
lcf_managed install --images ghcr --image-tag sha-0123456789ab
```

Host Runner 来自本地 checkout，而 API 来自镜像；协议升级后尤其应让 checkout 与镜像标签
来自同一提交或版本，避免宿主与容器协议错配。

切回本地源码构建：

```bash
lcf_managed install --images build
```

## 验证架构和镜像

在 M4 Mac 上：

```bash
docker image inspect \
  ghcr.io/fredgnr/local-context-forge-api:main \
  --format '{{.Os}}/{{.Architecture}}'
```

预期：

```text
linux/arm64
```

检查远端 manifest：

```bash
docker buildx imagetools inspect \
  ghcr.io/fredgnr/local-context-forge-api:main
```

输出应至少包含 `linux/amd64` 和 `linux/arm64`。启用 SBOM/provenance 后出现额外的
`unknown/unknown` attestation descriptor 是正常现象。

## 发布版本

只有桌面发行前置全部满足并已选定唯一版本时，才由 canonical owner 从受保护 `main` 创建
annotated、不可变的 `vX.Y.Z` tag。示意命令如下，执行前必须把两个占位符替换成同一个真实
版本并再次核对目标 commit：

```bash
git tag -a "vX.Y.Z" -m "Local Context Forge vX.Y.Z"
git push origin "vX.Y.Z"
```

推送后会并行发生两件事：

1. container workflow 发布 `X.Y.Z`、`X.Y`、`sha-<12位>`；
2. desktop workflow 等待 `macos-signing` 审批并尝试创建唯一 Draft，绝不会因 tag push 自动
   公开桌面 Release。

二者不是原子事务：容器镜像可能已经存在，而桌面构建仍等待审批或 fail closed。对外公告前必须
分别核对 GHCR digest、桌面 Draft 资产、物理 M4 门禁和最终 promotion。不要移动、删除或复用
失败版本的 tag；修复后提升版本。流水线不会自动创建 Git tag，也不会发布漂移含义不清的
`latest`。`main` 适合持续更新，精确 `X.Y.Z` 或 digest 适合稳定部署和回滚。

## 故障排查

`denied`、`unauthorized` 或 `Head ... 403`：

- 确认 PAT 是 classic token 且有 `read:packages`；
- 确认 `docker login` 使用的是 `fredgnr`；
- 组织启用 SSO 时，为 token 完成 SSO 授权；
- 检查 Package settings 的访问权限和仓库关联。

Actions 推送 `permission_denied: write_package`：

- 打开仓库 **Settings → Actions → General**，确认 Actions 未被禁用；
- 检查 workflow job 仍有 `packages: write`；
- 在 Package settings 的 **Manage Actions access** 中加入本仓库；
- 若同名包曾从命令行创建且未关联仓库，先手动连接本仓库。

M4 拉到 amd64：

```bash
docker context show
docker info --format '{{.Architecture}}'
docker image inspect \
  ghcr.io/fredgnr/local-context-forge-api:main \
  --format '{{.Architecture}}'
```

确认当前是 Apple Silicon 的 Docker Desktop/Colima context，并重新 `compose pull`。不要用
`platform: linux/amd64` 强制模拟运行，除非在专门排障。

官方参考：

- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
- [GitHub Actions 发布 Docker 镜像](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images)
- [Docker 多平台构建](https://docs.docker.com/build/ci/github-actions/multi-platform/)
- [Docker SBOM 与 provenance](https://docs.docker.com/build/ci/github-actions/attestations/)
