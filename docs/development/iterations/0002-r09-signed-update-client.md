# ITER-0002/R09：Signed update client

- 状态：`in-progress`
- 日期：2026-07-31
- 父迭代：[ITER-0002](0002-bundled-runtimes.md)
- 路线图关联：[ITER-0005](0005-updater-physical-gate.md)
- 决策：[ADR-0003](../../adr/0003-macos-release-signing-update-policy.md)、
  [ADR-0011](../../adr/0011-main-owned-signed-update-client.md)、
  [ADR-0014](../../adr/0014-two-stage-desktop-release-promotion.md)
- 需求：REQ-TRUST-001、REQ-RELEASE-001、REQ-RELEASE-002、REQ-UPDATE-001
- 验证：VAL-RELEASE-POLICY-001、VAL-RELEASE-PROMOTION-001、
  VAL-UPDATE-CLIENT-001、VAL-TRUST-001、VAL-UPDATE-001
- 当前决策：`source merge GO / release NO-GO`

## 目标与固定范围

这是 ITER-0002 的独立 R09 source 纵切：增加 Main-owned 的 signed update check/download，
以及用户确认后打开已验证 DMG 的 signed 路径。source/unprovisioned、校验或网络错误另有
用户显式触发的固定 canonical GitHub Releases 页面出口；它不下载或验证资产，也不改写 signed
updater 状态。renderer 只得到类型化、脱敏状态，不能提供或读取 URL、路径、公钥、签名、
header 或任意更新参数。

受保护发行工作流固定 exact tag/commit、macOS 15 arm64、锁定 runtime source、独立
Ed25519 update manifest、完整资产集合、SHA-256 和自签名 code-signing certificate。
私钥与证书只作为 `macos-signing` Environment 中的单个 versioned credential bundle；
`macos-release` 只允许 `main` branch promotion，不配置 Environment/repository release
secret 或长期签名凭据；promotion job 仍使用 GitHub 自动签发的短期 `GITHUB_TOKEN`。

本轮不配置生产 secret，不生成真实自签名 DMG，不证明 Gatekeeper，不执行发布，也不启用
automatic apply、静默安装、ZIP 执行或重启。未 provision 的 source/package 必须
fail closed。

## 任务

- [x] **R09-01 独立更新信任锚**：新增 unprovisioned/provisioned exact lock、
  Ed25519 public key audit、generation/digest 绑定和 `beforePack` fail-closed 检查。
- [x] **R09-02 Main 更新客户端**：固定仓库/API/channel/arch，canonical signed JSON、
  exact asset set、bounded redirect/download、私有 cache、hash/owner/mode/link 检查、
  原子 partial→ready 与打开前重验。
- [x] **R09-03 typed IPC/UI**：无参数 check/download/open、单飞/取消、稳定错误枚举，
  renderer 不得到 URL/path/key/signature/原始错误；独立 no-payload 操作只打开 Main 固定
  Release URL，失败不污染 updater 状态；UI 明示 automatic apply 不可用。
- [x] **R09-04 受保护 release policy**：tag-bound `macos-15` job、最小权限、
  `macos-signing` 唯一 Environment secret、`macos-release` 无配置 release secret/长期签名
  凭据且只使用短期 `GITHUB_TOKEN`、runtime/renderer/companion audit、自签名 DMG+ZIP
  组装、独立验证。
- [x] **R09-05 两阶段发布完整性**：desktop tag path 只上传一个已验证资产集合并创建/复核
  Draft；同 tag 的 GHCR workflow 独立且非原子；
  `workflow_dispatch --ref main` 的 trusted verifier 将输入 tag 隔离到 detached worktree，
  fresh-peel、重新下载、绑定 candidate manifest digest；在 `PATCH` 前以 fresh
  `origin/main` comparison ref 验证 promotion order，再以固定 Release ID 发布并做
  post-publish attestation/immutable/资产复核；不重新签名也不让 tag push 自动公开。
- [ ] **R09-06 物理门禁**：管理员 provision 生产 credential bundle，核验真实
  Environment/ruleset/Immutable Releases settings，并完成真实发布、clean-user
  DMG/Gatekeeper 和物理真实 `N-1 → N` 更新/fallback。

## 验收

- source/unpackaged、非 `darwin/arm64` 或 unprovisioned 构建不联网，状态为 unavailable；
- canonical manifest 签名覆盖 repo、version、channel、arch、source 和完整 update assets；
  extra/missing/duplicate 字段或资产、错误 key/generation/signature/hash/size 一律拒绝；
- 每个 redirect 重验 scheme/host/port/path/query，不转发凭据；manifest、header、body、
  asset、进度和错误均有上限；
- update cache 只接受私有目录中的 regular、owner-only、single-link 文件；symlink、
  hardlink、identity drift、partial 或 digest drift 不能复用/打开；
- renderer 无任意网络/路径/执行能力；只有显式用户动作可打开已验证 DMG；
- source/unprovisioned、signature/schema/asset/cache/digest 或网络错误仍让 signed updater
  fail closed；只有显式用户动作可打开固定 canonical Release 页面，renderer 无 URL，页面
  open 失败不覆盖 signed updater candidate/error 状态；
- release workflow 只从 exact `v*.*.*` tag 构建，普通 PR/fork/source job 无 secret；
  desktop tag path 只能创建经远端完整性校验的 Draft，永远不能公开 desktop Release；
  相同 tag 的 GHCR 发布须独立核对；
- build/sign 绑定 tag-only `macos-signing`，Draft job 无 Environment/secret；公开只能由
  branch-only、无配置 release secret/长期签名凭据的 `macos-release`
  `workflow_dispatch --ref main` 执行；job 仍使用短期 `GITHUB_TOKEN`，`release_tag`
  只是资料输入；
- trusted `main` verifier 使用隔离 tag worktree、fresh peel 和固定 Release ID，重新下载 Draft
  并将人工确认的 candidate manifest digest 与公开前后资产集合绑定；任何已 published 预状态
  都是发布安全事件，不按幂等成功；
- 两个 Environment 必须有独立 reviewer、prevent self review、UI admin bypass disabled；
  `protected-main`、owner-only `release-tag-creation`、无 bypass `immutable-release-tags`
  ruleset 和 GitHub Immutable Releases 都必须生效；
- `release-manifest.json` 必须明确 `hardenedRuntime=false`、`notarized=false`、
  `stapled=false` 和 `automaticApply.enabled=false`。

## 验证日志

| 验证 | 结果 | 日期/提交 | 命令或过程 | 证据/说明 |
| --- | --- | --- | --- | --- |
| VAL-RELEASE-POLICY-001 Desktop | `pass` | 2026-07-31；`71890ee` source checkpoint | `cd desktop && ./node_modules/.bin/vitest run tests/releasePolicy.test.ts tests/updateTrustPackaging.test.ts` | 2 files / 18 pass；本地/远端资产、promotion order、Draft/Published、candidate digest 和 update trust source contract |
| VAL-RELEASE-POLICY-001 Backend | `pass` | 2026-07-31；`71890ee` source checkpoint | `backend/.venv/bin/pytest -q tests/backend/test_desktop_release_bootstrap.py tests/backend/test_desktop_release_workflow_policy.py` | 22 pass；source 合同：job/event/权限、两个 Environment、release workflow 唯一 private credential、ruleset/Immutable Releases 与两阶段远端复核；真实 settings `not-run` |
| VAL-RELEASE-PROMOTION-001 | `pass` | 2026-07-31；`71890ee` source checkpoint | 上述 Desktop/Backend focused commands；YAML parse；17 个 workflow `run` script `bash -n` | source 合同：desktop tag path Draft-only、main-only promotion、trusted verifier/隔离 worktree/fresh peel、PATCH 前 fresh `origin/main` promotion order、固定 Release ID、published 预状态拒绝、post-publish attestation/immutable；同 tag GHCR 独立非原子；真实 promotion `not-run` |
| VAL-UPDATE-CLIENT-001 Desktop | `pass` | 2026-07-31；`fcca1e4` | `cd desktop && ./node_modules/.bin/vitest run tests/updateClient.test.ts tests/updateIpc.test.ts tests/updateTrustPackaging.test.ts tests/preload.test.ts tests/beforePack.test.ts` | 5 files / 42 pass；签名/schema/redirect/cache/tamper/IPC/open 前重验、固定 Release action 与状态保持 |
| VAL-UPDATE-CLIENT-001 Web | `pass` | 2026-07-31；`fcca1e4` | `cd web && ./node_modules/.bin/vitest run src/App.test.tsx src/desktopBridge.test.ts` | 2 files / 19 pass；状态/确认、手工 Release 出口脱敏和 browser fail-closed |
| Desktop full | `pass` | 2026-07-31；`71890ee` source checkpoint | `cd desktop && npm test -- --run` | 30 files / 245 pass / 7 skip |
| Web full | `pass` | 2026-07-31；`fcca1e4` | `cd web && npm test -- --run` | 7 files / 51 pass |
| VAL-TRUST-001 packaged updater | `not-run` | — | 需 provisioned protected build 与 packaged renderer 审计 | source contract 不证明真实包 |
| VAL-UPDATE-001 | `not-run` | — | 需物理 Apple Silicon 真实 `N-1 → N` 与失败 DMG fallback | automatic apply 保持禁用 |

## 风险与回滚点

| 风险 | 缓解/回滚点 |
| --- | --- |
| 公钥/证书尚未 provision | signed update client 和 formal build fail closed；用户仅可显式打开固定 Release 页面，不把页面当成已验证资产 |
| GitHub API/redirect 行为变化 | exact host/path/query 和 bounded redirects；不放宽为任意 URL |
| 自签名且未 notarize 的应用触发 Gatekeeper 警告 | release manifest/notes 明示限制；真实 clean-user gate 通过前不宣称可发布 |
| 下载后缓存被同 uid 进程替换 | single-link/owner/mode/identity/hash 在复用和 open 前重验；仍不宣称 OS 级隔离 |
| ZIP/electron-updater metadata 被误当自动 apply 授权 | 更新客户端只打开 DMG；manifest 明确 automatic apply false |
| desktop 发布资产在上传后漂移 | desktop tag path 停止在 Draft；promotion 重新下载并绑定 candidate digest，以固定 Release ID 公开并在前后复核；GHCR workflow 独立记录 |
| 从 release tag 执行被削弱 verifier | dispatch ref 固定 protected `main`；tag 只作为 data 放入隔离 worktree，workflow script 始终来自 trusted main |
| 并行 tag promotion 沿用旧 HEAD 计算 latest | `verifyPromotionOrder` 在 `PATCH` 前以 fresh-fetched `origin/main` comparison ref 重算 SemVer 顺序和 `make_latest` |
| Draft 在最终校验到公开间被 writer 修改 | GitHub Draft 无资产 CAS；published 后立即执行 `gh release verify`/immutable/完整集合复核，发现差异按发布安全事件处理，不静默覆盖或重跑洗绿 |
| owner/writer/管理员改变信任控制 | 明确其为根信任；ruleset/reviewer 缩小权限但不宣称能抵御恶意根信任 |

## 当前变更清单

- `docs/adr/0011-main-owned-signed-update-client.md`
- `docs/adr/0014-two-stage-desktop-release-promotion.md`
- `docs/development/{desktop-release,traceability}.md`
- `docs/development/iterations/0002-r09-signed-update-client.md`
- `README.md`、`SECURITY.md`、`desktop/README.md`
- `docs/{04-quickstart,10-security,14-all-in-one-macos,16-electron-desktop-guide}.md`
- `.github/workflows/desktop-release.yml`
- `.github/desktop-release-notes.md`
- `tools/bootstrap_desktop_release_keys.py`
- `runtime/{update-metadata-key,macos-codesign-certificate}.lock.json`
- `desktop/resources/update/**`
- `desktop/src/main/{updateClient,updateIpc,index}.ts`
- `desktop/src/{contracts}.ts`
- `desktop/src/preload/index.ts`
- `desktop/scripts/{auditUpdateTrust,beforePack,prepareRelease}.cjs`
- `desktop/{electron-builder,electron-builder.release}.yml`
- `desktop/tests/{releasePolicy,updateClient,updateIpc,updateTrustPackaging,preload,beforePack}.test.ts`
- `web/src/{App,App.test}.tsx`
- `web/src/{desktopBridge,desktopBridge.test}.ts`
- `web/src/styles.css`

R09 的 source `[x]` 不改变 ITER-0004/0005 的状态。两个 Environment、ruleset 和 Immutable
Releases 的真实 settings，真实签名产物、干净用户安装和物理跨版本门禁仍为 `not-run`；
当前整体结论保持 **source merge GO / release NO-GO**。
