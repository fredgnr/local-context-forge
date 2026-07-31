# macOS desktop release runbook

本 runbook 面向 `fredgnr/local-context-forge` 维护者，说明已实现但尚未完成物理交付门禁的
macOS arm64 release workflow。当前 public trust locks 为 `unprovisioned`，因此 formal
release 会 fail closed。source tests 或普通 macOS CI 不能替代 protected build、干净用户
安装和物理更新证据。

决策与证据：

- [ADR-0003：macOS release policy](../adr/0003-macos-release-signing-update-policy.md)
- [ADR-0011：signed update client](../adr/0011-main-owned-signed-update-client.md)
- [ITER-0002/R09](iterations/0002-r09-signed-update-client.md)
- [追踪矩阵](traceability.md)

## 发行模型

- 唯一正式入口：`.github/workflows/desktop-release.yml`；
- runner：`macos-15`，目标只允许 `darwin/arm64`；
- tag：exact `v*.*.*`，必须解析到 workflow checkout 的同一 commit；
- protected Environment：`macos-release`，应配置 required reviewers 和 tag deployment
  policy；
- 唯一 release secret：`DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`；
- code signing identity：`Local Context Forge Self Signed`；
- 当前明确 `hardenedRuntime=false`、`notarized=false`、`stapled=false`；
- update metadata 使用独立 Ed25519 key；automatic apply 固定为 disabled。

普通 PR、fork 和 source CI job 只有 `contents: read`，不能引用 Environment secret。
正式 release build/sign job 绑定 `macos-release` Environment 并读取唯一 credential bundle；
publish job 只有在 build/asset verification 成功后才获得 `contents: write`，且不读取该 secret。

当前仓库尚无由此流程产出的真实 tag、DMG 或公开 Release，也没有 Developer ID/notarization。
source/unprovisioned、校验或网络错误时，应用的 signed update check/download 继续 fail closed；
只有用户显式操作可让 Main 打开固定 canonical Releases 页面。Renderer 无 URL，该操作也不
改变 signed updater 状态；维护者和用户都不得把它当作已验证资产或成功发布的证据。

## 首次 provision 或轮换

必须由有权管理 canonical repository Environment 的管理员在可信主机操作。先确认
`macos-release` 的 reviewer/tag policy 已启用、`gh auth status` 指向正确账号，并使用干净
checkout。不要在聊天、issue、日志或 shell history 中传递 credential bundle。

查看工具合同：

```bash
python tools/bootstrap_desktop_release_keys.py --help
```

首次生成并通过 stdin 上传一个 versioned credential bundle：

```bash
python tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload
```

有意轮换时额外使用 `--rotate`。脚本只把以下 public artifacts 写入仓库：

- `desktop/resources/update/update-metadata-ed25519-public.pem`
- `runtime/update-metadata-key.lock.json`
- `runtime/macos-codesign-certificate.lock.json`

私有 Ed25519 key、PKCS#12、certificate password 和 base64 credential bundle 不得提交。
默认私有目录为 mode-0700、文件为 mode-0600；使用 `--upload` 且 public pins 事务成功后，
脚本会删除该目录。若 secret 已上传但 public pins 提交失败，formal release 会因 generation/
digest 不匹配 fail closed；保留恢复目录，修复后按脚本错误提示完成显式 rotation。

只提交并评审上述三个 public artifacts。评审至少核对：

- 两个 lock 都为 `status: provisioned`；
- 相同的 32-hex `credentialGenerationId`；
- public key 是 Ed25519，PEM SHA-256 与 update lock 一致；
- certificate SHA-256、固定 identity 与 credential bundle generation 一致；
- diff 中没有 private key、P12、password、bundle 或额外 secret。

## 发布前检查

1. 版本在 `runtime/version.json`、package 和协议层同步，release notes 已更新。
2. 目标 commit 已合并，working tree clean，准备 annotated/exact `vX.Y.Z` tag。
3. `macos-release` Environment、reviewers、tag policy 和 credential bundle generation
   与已提交 public pins 一致。
4. 所有 source 门禁通过；任何物理门禁仍如实记录为 `not-run`，不能由此 workflow 推断。
5. 已知限制保留在 `.github/desktop-release-notes.md`：自签名、未 notarize、未启用
   hardened runtime、automatic apply disabled。

可在 source checkout 运行不接触 secret 的策略检查：

```bash
node desktop/scripts/prepareRelease.cjs preflight --tag "vX.Y.Z"
cd desktop
npm test -- --run
npm run typecheck
cd ../backend
.venv/bin/pytest -q \
  ../tests/backend/test_desktop_release_bootstrap.py \
  ../tests/backend/test_desktop_release_workflow_policy.py
```

## 触发与审批

推送 exact `vX.Y.Z` tag 会运行 build/sign/verify，并在成功后进入 publish job。也可在该
tag ref 上手动 dispatch：

- `publish=false`：只生成并上传 workflow artifact，不创建 GitHub release；
- `publish=true`：通过 Environment 审批后创建、远端复核并发布 release。

不要从 branch ref dispatch，也不要重用已存在 release 的 tag。workflow 会：

1. 绑定 tag、commit 和 `SOURCE_DATE_EPOCH`；
2. 下载并双重校验固定 CPython 3.13.14 与 Node 22.23.2 source archives；
3. 构建/审计 Python sidecar、QMD、renderer、MCP companion 和 Electron source；
4. 在临时 keychain 中导入 credential bundle，验证 generation/digest；
5. 生成自签名 arm64 DMG、electron-updater ZIP/blockmap/metadata；
6. 生成 canonical `update-manifest.json` 及 detached Ed25519 signature；
7. 生成 `release-manifest.json`、`SHA256SUMS`、runtime inventory/SBOM/notices；
8. 对完整资产目录独立 `verify-assets`，再上传一个无压缩 workflow artifact；
9. publish job 重新下载并验证，创建 draft，逐项核对 GitHub 远端 name/size/
   `sha256:` digest/download URL；只有完整集合一致才将 draft 公开。

任一步失败都停止。不要手工删减、替换或追加 draft assets 后再发布；删除失败 draft，
修复代码/配置，使用新 tag 重建。

## 资产核验

下载 workflow artifact 或 release assets 到一个新的绝对目录，然后运行：

```bash
node desktop/scripts/prepareRelease.cjs verify-assets \
  --tag "vX.Y.Z" \
  --asset-dir "/absolute/path/to/new-release-assets"
```

资产集合包括 arm64 DMG、ZIP、blockmap、`<channel>-mac.yml`、canonical update manifest 与
signature、release manifest、`SHA256SUMS`、public update key，以及 Python/QMD 的 build
manifest 和 SBOM、MCP/renderer build manifest。更细的 inventory/notices 由相应 build
manifest/SBOM 记录，不作为独立 Release asset。以 `release-manifest.json` 和工具的 exact
membership 检查为准，不手工猜测文件数量。

额外人工核对：

- manifest 的 repository/tag/version/commit/arch/generation；
- DMG/app 和所有 native runtime 均为 arm64；
- app/sidecar 的 code-sign identity/certificate digest；
- update manifest signature 和每个资产 size/SHA-256；
- `automaticApply.enabled=false` 与非 notarized/hardened 限制；
- GitHub release 的资产集合与本地验证目录完全一致。

## 物理 Mac 门禁

下列项目在真实证据上传并映射到追踪矩阵前必须保持 `not-run`：

- protected `macos-15` arm64 full DMG/ZIP build 与真实 credential bundle；
- clean Apple Silicon 用户安装、首次 Gatekeeper 流程、核心 smoke 和无外部
  Docker/Homebrew/Python/Node/Git/ctags；
- packaged Python/QMD/MCP 的真实 UDS、崩溃/重启和应用退出生命周期；
- QMD 真实模型首次下载、离线/低磁盘/中断、forced rebuild、hybrid 和 profile switch；
- 官方签名 Codex 的一键 MCP 接入、Codex 重启、两个工具、app move/reconnect/clear；
- 本地 home/外置卷/私有仓库、移动/删除目录和 app 重启；
- 0.0.1 创建数据 → 0.0.2 跨版本、数据保留、自动路径失败注入和 verified DMG fallback；
- fork/PR/普通 workflow 无法读取 `macos-release` secret 的仓库设置证据。

在这些门禁通过前，DMG 不是一般可用发布结论，automatic apply 不得启用。失败时保留
workflow artifact、release manifest、Actions run URL 和脱敏测试记录；不要上传 keychain、
credential bundle、私钥、P12、password、用户数据或绝对本地路径。
