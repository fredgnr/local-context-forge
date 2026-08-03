# macOS desktop release runbook

本 runbook 面向 `fredgnr/local-context-forge` 维护者，说明已实现但尚未完成物理交付门禁的
macOS arm64 release workflow。当前 public trust locks 为 `unprovisioned`，因此 formal
release 会 fail closed。source tests 或普通 macOS CI 不能替代 protected build、干净用户
安装和物理更新证据。

本页只适用于 W14–W16 的 formal release，不适用于 W02 packaged smoke 或 W03 engineering
test package。Engineering artifacts 必须使用独立 non-release mode，不读取 production
credential/pins、不由 tag 触发、不上传、不创建 Draft/Release，updater unavailable/no-network。

> [ADR-0015](../adr/0015-electron-only-legacy-retirement.md) 已决定删除 container/GHCR 发布面。
> 本页的同-tag GHCR 说明只记录删除前的当前风险；`TODO-LEGACY-REMOVE-RELEASE-001` 完成后
> 必须移除这些步骤。首个受支持 Electron-only 公开 Release 还要求
> exact Draft 上的 `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001` 与
> `VAL-RELEASE-CONTINUITY-001=pass`。

> **操作停止：** 在 [ADR-0016](../adr/0016-pre1-incremental-retirement-engineering-package.md)
> 的 W13 final rebuilt bytes 同时取得 `VAL-ELECTRON-CUTOVER-001=pass` 与
> `VAL-LEGACY-ABSENCE-001=pass` 前，不得配置本页 production control plane、provision
> credential/trust pins，也不得执行 tag、Draft 或 promotion。下文同-tag/GHCR 段落是审计
> 现状，不是当前可执行 runbook。

决策与证据：

- [当前状态](status.md)
- [部署与运维总手册](../18-deployment-operations.md)
- [剩余任务](todo.md)
- [证据记录规范](evidence/README.md)
- [ADR-0003：macOS release policy](../adr/0003-macos-release-signing-update-policy.md)
- [ADR-0011：signed update client](../adr/0011-main-owned-signed-update-client.md)
- [ADR-0014：two-stage release promotion](../adr/0014-two-stage-desktop-release-promotion.md)
- [ADR-0016：incremental retirement / engineering package boundary](../adr/0016-pre1-incremental-retirement-engineering-package.md)
- [W01–W16 work plan](work-plan.md)
- [ITER-0002/R09](iterations/0002-r09-signed-update-client.md)
- [追踪矩阵](traceability.md)

## 发行模型

- 唯一正式入口：`.github/workflows/desktop-release.yml`；
- runner：`macos-15`，目标只允许 `darwin/arm64`；
- build/sign 只响应 exact `v*.*.*` tag push；
- `macos-signing`：只允许 tag `v*.*.*`，保存本工作流唯一的 private credential
  `DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`；
- `macos-release`：只允许 branch `main`，Environment/repository release secret 集合必须为空，
  不保存长期签名凭据；promotion job 仍使用 GitHub 自动签发的短期 `GITHUB_TOKEN`；
- 两个 Environment 都必须有 required reviewers、`prevent self review`，并在 GitHub UI
  禁止 administrator bypass；
- code signing identity：`Local Context Forge Self Signed`；
- 当前明确 `hardenedRuntime=false`、`notarized=false`、`stapled=false`；
- update metadata 使用独立 Ed25519 key；automatic apply 固定为 disabled。

普通 PR、fork 和 source CI job 只有 `contents: read`，不能引用 Environment secret。
正式 release build/sign job 绑定 `macos-signing` Environment 并读取本工作流唯一的
credential bundle；
desktop workflow 在 tag push 后的 Draft job 只有 `contents: write`，不绑定 Environment 且
不读取该 secret；它只产生经远端复核的 **desktop Draft**，不会公开 desktop Release。相同
tag 还会独立触发 container workflow 的 GHCR SemVer 发布；两条 workflow 并行且非原子，
container image 可能在 desktop 审批等待或失败时已经公开。

公开是第二次、独立的手动 promotion。维护者必须用 `workflow_dispatch --ref main` 启动受
`protected-main` ruleset 保护的 verifier；`release_tag` 只是资料输入，不能决定 workflow
代码来源。promotion 绑定无配置 release secret/长期签名凭据的 `macos-release`
Environment，不依赖 build job、不重新签名，也不引用任何 `secrets.*`；它仍使用 GitHub
自动签发的短期 `GITHUB_TOKEN`。可信 `main` verifier 把 tag 隔离到 detached worktree、
fresh-peel tag、固定 Draft Release ID，并且只有这个 job 可以用 REST `PATCH` 公开该 ID。

当前仓库尚无由此流程产出的真实 tag、DMG 或公开 Release，也没有 Developer ID/notarization。
source/unprovisioned、校验或网络错误时，应用的 signed update check/download 继续 fail closed；
只有用户显式操作可让 Main 打开固定 canonical Releases 页面。Renderer 无 URL，该操作也不
改变 signed updater 状态；维护者和用户都不得把它当作已验证资产或成功发布的证据。

## 首次 provision 或轮换

本节从 W14 开始：先验证 GitHub controls，随后在 W15 provision。W13 前即使管理员权限可用，
也不得提前执行。

必须由有权管理 canonical repository 设置的管理员在可信主机操作。先在 GitHub UI 确认两个
Environment 都禁止 admin bypass，并配置下列 fail-closed 控制：

- `macos-signing`：required reviewers、prevent self review、唯一 tag policy `v*.*.*`，
  且该 Environment 的 release workflow credential 集合只有一个 credential bundle secret；
- `macos-release`：required reviewers、prevent self review、唯一 branch policy `main`，
  Environment/repository release secret 集合为空、无长期签名凭据；job 仅使用短期
  `GITHUB_TOKEN`；
- active `protected-main` branch ruleset：PR、至少一名独立 review、dismiss stale reviews、
  last-push approval、resolve threads、禁止 force push/delete、无 bypass；
- active `release-tag-creation` ruleset：`refs/tags/v*.*.*` 只能由 canonical owner actor
  通过 creation-only bypass 创建；
- active `immutable-release-tags` ruleset：release tag 禁止 update/delete，且无 bypass；
- GitHub Immutable Releases 已开启。

确认 `gh auth status` 指向正确账号并使用干净 checkout。不要在聊天、issue、日志或 shell
history 中传递 credential bundle。

查看工具合同：

```bash
python tools/bootstrap_desktop_release_keys.py --help
```

首次生成并通过 stdin 上传一个 versioned credential bundle：

```bash
python tools/bootstrap_desktop_release_keys.py \
  --repo fredgnr/local-context-forge \
  --upload \
  --confirm-admin-bypass-disabled
```

`--confirm-admin-bypass-disabled` 是操作者已在 UI 核对两个 Environment 的显式声明；bootstrap
仍会通过 API 校验 repository、Environment、ruleset、secret membership 和 Immutable Releases，
但这些 source/API 检查不等于真实设置证据已完成。有意轮换时额外使用 `--rotate`。脚本只把
以下 public artifacts 写入仓库：

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

“唯一 credential”只限定 `desktop-release.yml` 的正式签名输入和 `macos-signing`
Environment 的成员资格，不声称仓库、账号或组织没有其他无关 secret。

### 设置精确性与证据

bootstrap 的校验必须匹配**完整合同**，不能只看到同名对象就通过：

- Environment 名称、deployment branch/tag policy、required reviewer、prevent-self-review
  与 secret name/membership；
- `protected-main`、`release-tag-creation`、`immutable-release-tags` 的 `active` enforcement、
  ref condition、所需 rule 类型、bypass actor/mode 和禁止 force/delete；
- GitHub Immutable Releases 的真实开启状态；
- 操作者在 UI 中确认 admin bypass 已关闭。

API 可见字段保存为脱敏 JSON，UI-only 控制保存截图；两者都按
[证据记录规范](evidence/README.md)绑定 repository、观察时间、操作者角色和目标 commit。
截图必须裁掉通知、账号隐私、secret value 和无关仓库。只有配置存在但没有 exact-value
验证，仍记为 `not-run`，不能把 `VAL-SECRET-001` 标为 `pass`。

## 发布前检查

1. 版本在 `runtime/version.json`、package 和协议层同步，release notes 已更新。
2. 目标 commit 已合并，working tree clean，准备 annotated/exact `vX.Y.Z` tag。
3. `macos-signing`/`macos-release` 的 reviewer、prevent-self-review、tag/branch policy、
   secret membership 和 UI admin-bypass 状态均符合上节；credential bundle generation 与
   已提交 public pins 一致。
4. 所有 source 门禁通过；任何物理门禁仍如实记录为 `not-run`，不能由此 workflow 推断。
5. 已知限制保留在 `.github/desktop-release-notes.md`：自签名、未 notarize、未启用
   hardened runtime、automatic apply disabled。
6. 明确接受两次审批：第一次授权 secret-bound 候选构建，第二次只授权 exact candidate
   digest 的公开 promotion。两次审批之间不得编辑、覆盖或追加 Draft 资产。
7. `protected-main`、`release-tag-creation`、`immutable-release-tags` 都是 active、pattern/
   rule/bypass 精确匹配，并已开启 GitHub Immutable Releases。
8. 已记录 W13 checkpoint commit/package digest；checkpoint → formal tag 的 diff 只包含审核过的
   production public pins、release metadata 与版本变更，没有 runtime logic 或 legacy surface；
   formal tag 的 source/aggregate absence 重跑已通过。否则回到 W13，不得创建候选。该 W15
   continuity verifier/evidence 尚未实现且当前为 `not-run`；它必须在 W13 checkpoint 前落地并
   冻结。若到 W15 才新增/修改，必须建立新 W13 checkpoint 并重跑。
   现有 workflow 没有 checkpoint 输入，不会自动执行此检查。

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

### 阶段一：构建候选并停止在 Draft

这是统一产品发行事件，不是仅 desktop 的操作。同一 exact `vX.Y.Z` tag 会同时启动 GHCR
container workflow 与下述 desktop workflow；二者没有跨 workflow 事务或回滚。创建 tag 前
必须同时确认 container 与 desktop 版本/发布说明已就绪，并准备分别记录两个 run 和 digest。

由 canonical owner 从受保护 `main` 创建并推送 exact tag；`macos-signing` Environment
第一次审批后，desktop workflow：

1. 绑定 tag、commit 和 `SOURCE_DATE_EPOCH`；
2. 下载并双重校验固定 CPython 3.13.14 与 Node 22.23.2 source archives；
3. 构建/审计 Python sidecar、QMD、renderer、MCP companion 和 Electron source；
4. 在临时 keychain 中导入 credential bundle，验证 generation/digest；
5. 生成自签名 arm64 DMG、electron-updater ZIP/blockmap/metadata；
6. 生成 canonical `update-manifest.json` 及 detached Ed25519 signature；
7. 生成 `release-manifest.json`、`SHA256SUMS`、runtime inventory/SBOM/notices；
8. 对完整资产目录独立 `verify-assets`，再上传一个无压缩 workflow artifact；
9. Draft job 重新下载并验证；exact tag 无 Release 时创建 Draft。若前次创建响应丢失且已
   留下唯一 Draft，只在它与本次同 tag 重建候选完整一致时恢复；published、重复或漂移均拒绝；
10. 逐项核对 GitHub 远端 tag/title/state/notes 与 name/size/`sha256:` digest/download URL
    完整集合，然后停止，全程不覆盖现有 Release。

以上是当前 source workflow 的既有行为；它不实现发布前检查第 8 项。machine-checkable
continuity verifier 必须在 W13 前实现、审查并冻结；若 W15 才补齐，就先回到 W13 建立并复验
新 checkpoint。只有其独立、可复现 evidence 通过后才允许创建 tag。

tag push 永远不会公开 **desktop GitHub Release**，但 GHCR workflow 可能已经公开同版本
container image。任一步失败都停止；记录这种非原子部分成功，不要手工删减、替换、追加或
`--clobber` Draft assets。若构建、验证或真机测试发现问题，不移动旧 tag，也不复用该候选；
修复 `main`、提升版本并创建新 tag。分别核对 container run/image digest 与 desktop
build/Draft run，不能用其中一条的成功替代另一条。

### 阶段二：真机验证并手动推广

1. 从 Draft 下载完整资产到新的私有目录，先运行下方 `verify-assets`。
2. 在目标 M4 上以**将要公开的 exact Draft digest**重新运行完整
   `VAL-ELECTRON-CUTOVER-001`、`VAL-LEGACY-ABSENCE-001`，并完成 clean-user、Gatekeeper、
   packaged runtime、Codex、embedding 和 update 测试；不得复用 W13 engineering package 结果。
3. 记录候选 manifest 的小写 SHA-256：

   ```bash
   shasum -a 256 "/absolute/path/to/release-assets/release-manifest.json"
   ```

4. 只有 `VAL-RELEASE-CONTINUITY-001=pass` 且所有测试结论允许公开时，才从 trusted `main`
   手动运行 workflow。`--ref` 必须固定为 `main`；`release_tag` 只是要验证的 exact tag 资料，
   digest 必须是上一步的 64 位小写值：

   ```bash
     gh workflow run desktop-release.yml \
       --repo fredgnr/local-context-forge \
     --ref main \
     -f release_tag="vX.Y.Z" \
     -f candidate_manifest_sha256="<64位小写SHA-256>" \
     -f confirm_publish=true
   ```

   所有 tag 的 promotion 共用一个不自动取消的全局 concurrency group，会按队列串行执行。

5. 在无配置 release secret/长期签名凭据的 `macos-release` Environment 中完成第二次审批；
   job 仅使用短期 `GITHUB_TOKEN`。promotion 必须证明 `GITHUB_SHA` 是 fresh `main` head，
   从私有 ref fresh-peel 输入 tag，在 detached worktree
   中读取 tag-bound data，并验证 tag commit 属于 `main` 历史。
6. promotion 严格选出唯一 exact Draft，记录 Release ID，下载全部资产；公开前再次 fresh
   fetch tag/Release 和 `origin/main`，并要求 tag、Draft 状态和固定 ID 都未变化。
   `verifyPromotionOrder` 必须以这次 `PATCH` 前 fresh-fetched `origin/main` comparison ref
   计算版本顺序/`make_latest`，不得沿用运行启动时的旧 HEAD，避免并行 tag promotion 把旧版本
   设为 latest。唯一 mutation 是对这个 ID 执行
   `PATCH {"draft":false,"make_latest":...}`。
7. `PATCH` 后再次 fresh-peel tag，运行 `gh release verify`，并核对同一 Release ID 的
   `immutable=true`、published state、notes 和完整资产集合。

不要从 tag ref 或 `main` 以外的 branch dispatch，也不要把 `confirm_publish=false` 当成构建
模式；手动 dispatch 从不重建候选。若 Draft 不存在、已经被编辑、资产不完整、digest 不一致、
tag 漂移或 Release ID 改变，promotion 必须 fail closed。promotion 开始时若 exact Release
已经 published，无论资产看似是否一致，都必须作为发布安全事件处理；不得重跑来“幂等洗绿”。
W13 checkpoint/tag diff、tag source/absence 或 exact Draft cutover/absence 证据缺失/漂移时同样
fail closed。

## 资产核验

下载 workflow artifact 或 release assets 到一个新的绝对目录，然后运行：

```bash
node desktop/scripts/prepareRelease.cjs verify-assets \
  --tag "vX.Y.Z" \
  --asset-dir "/absolute/path/to/new-release-assets"
```

工作流还会把 GitHub 返回的 Release JSON 与同一资产目录交给
`verify-github-release`。该命令分别验证 `draft` 和 `published` 状态，并拒绝错误 tag/title/
prerelease/notes/Release ID/immutable state、重复或额外资产、非 `uploaded` state、
size/digest/URL 漂移。promotion 额外传入人工记录的 candidate manifest digest；不要用浏览器
页面外观替代该检查。

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

repository owner、能改 `main`/workflow 的 `contents` writer 和设置管理员仍是根信任。
ruleset 与 reviewer 不会防御恶意根信任。GitHub Draft 也没有资产 CAS：即使 fixed Release ID
在最终复核后才 `PATCH`，writer 仍可能在 verify→PATCH 的短窗口修改 Draft。Immutable Releases
只保护 published 状态；post-publish `gh release verify`、`immutable=true` 和完整资产复核只能
后验检测。若发现差异，立即停止公告与 update feed、保留证据并按发布安全事件升级；不得编辑
既有 Release、覆盖 tag 或用重跑洗绿。

## 物理 Mac 门禁

下列项目在真实证据上传并映射到追踪矩阵前必须保持 `not-run`：

- protected `macos-15` arm64 full DMG/ZIP build 与真实 credential bundle；
- clean Apple Silicon 用户安装、首次 Gatekeeper 流程、核心 smoke 和无外部
  Docker/Homebrew/Python/Node/Git/ctags；
- packaged Python/QMD/MCP 的真实 UDS、崩溃/重启和应用退出生命周期；
- QMD 真实模型首次下载、离线/低磁盘/中断、forced rebuild、hybrid 和 profile switch；
- 官方签名 Codex 的一键 MCP 接入、Codex 重启、两个工具、app move/reconnect/clear；
- 本地 home/外置卷/私有仓库、移动/删除目录和 app 重启；
- 真实上一版本 `N-1` 创建数据 → 真实单调下一版本 `N`、数据保留、更新路径失败注入和
  verified DMG fallback；早期 ADR 的版本号只是示例；
- 两个 Environment、三组 ruleset、Immutable Releases 和 fork/PR/普通 workflow secret
  隔离的真实 GitHub settings 证据。

在这些门禁通过前，DMG 不是一般可用发布结论，automatic apply 不得启用。失败时保留
workflow artifact、release manifest、Actions run URL 和脱敏测试记录；不要上传 keychain、
credential bundle、私钥、P12、password、用户数据或绝对本地路径。

因此当前整体结论保持 **source merge GO / release NO-GO**：source contract 可合并；真实
settings、protected signing/promotion、签名 DMG 和物理 Mac 证据均仍为 `not-run`。
