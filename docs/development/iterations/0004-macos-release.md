# ITER-0004：macOS release foundation

- 状态：`planned`
- 依赖：W13 final cutover/absence；W14 production control plane；ITER-0001–0003 的相关门禁
- 路线图阶段：P5

## 目标与范围

本迭代只承载 W14–W16 formal release；不承载 W02/W03 engineering artifacts。W13 前不得执行
P02/P02a 或 credential provisioning，不得创建 release tag/Draft。

交付 macOS Apple Silicon arm64 DMG。build/sign 只由 `v*.*.*` tag push 进入
`macos-signing`，该 Environment 保存仓库唯一 credential bundle secret；Draft job 不绑定
Environment/secret。公开必须在真机测试后由 `workflow_dispatch --ref main` 进入 branch-only、
无配置 Environment/repository release secret 或长期签名凭据的 `macos-release`；promotion
job 仍使用 GitHub 自动签发的短期 `GITHUB_TOKEN`。它以 `release_tag` 作为资料输入，由 trusted
`main` verifier 对隔离 tag worktree 和 fixed Release ID 完成。明确披露不 notarize、不启用
hardened runtime。

## 计划任务

- [x] P01a source foundation：arm64 DMG/ZIP、资源清单、版本、摘要、Draft/promotion workflow
  和 fail-closed policy 已实现并通过 source tests。
- [ ] P01b 使用 provisioned credential 在受保护 macOS runner 生成真实签名资产。
- [ ] P01c 记录 W13 checkpoint → formal tag 的 allowlisted public pins/release metadata/version
  diff，在 tag 重跑 source/aggregate absence，并把 exact Draft digest 绑定到 continuity evidence。
- [ ] P02 配置两个受保护 Environment：都 required reviewers、prevent self review、UI 禁
  admin bypass；`macos-signing` 只允许 tag `v*.*.*`/唯一 secret，`macos-release` 只允许
  branch `main`/无配置 Environment/repository release secret 或长期签名凭据；promotion
  job 仍使用短期 `GITHUB_TOKEN`。
- [ ] P02a 配置 active `protected-main`（PR、独立 approval、dismiss stale、last-push
  approval、resolve threads、no force/delete、no bypass）、owner-only
  `release-tag-creation`、no-bypass `immutable-release-tags`，并开启 GitHub Immutable
  Releases。
- [x] P03a source foundation：授权 job 的临时 keychain 导入/清理流程已有 source contract。
- [ ] P03b 在真实 credential build 中验证 keychain、nested signing 和清理。
- [ ] P04 验证 PR、fork 和普通 CI 均无法读取发布秘密。
- [ ] P05 在无外部运行时的干净 Apple Silicon Mac 完成安装 smoke。
- [x] P06a source foundation：trusted-main、detached worktree、fresh peel、fixed ID、
  promotion order 和 post-publish validator 已实现。
- [ ] P06b 从同一 Draft 下载物理测试候选，记录 `release-manifest.json` SHA-256，在 exact Draft
  digest 重新运行完整 cutover/absence（不得复用 W13 engineering evidence），经第二次
  Environment 审批；以 `--ref main` 启动 trusted verifier，隔离/fresh-peel tag，固定 Release
  ID；在 `PATCH` 前以 fresh `origin/main` comparison ref 验证 promotion order/`make_latest`，
  再执行 REST `PATCH`、post-publish `gh release verify`、immutable 和完整资产复核。
- [x] P07a source policy：published 预状态、tag/Release ID/asset 漂移和 post-publish
  mismatch 的拒绝合同已测试。
- [ ] P07b 在真实 Draft/promotion 控制面演练上述安全事件，不允许重跑幂等洗绿。

`[x]` 只表示提前落地的 R09 source foundation，不改变本迭代 `planned` 状态。真实任务见
[TODO-REL-*](../todo.md)。
安全事件 fail closed，不能重跑幂等洗绿。

## 退出门禁

- VAL-RELEASE-CONTINUITY-001、VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001 为 `pass`；
- exact Draft digest 上的 VAL-ELECTRON-CUTOVER-001 与 VAL-LEGACY-ABSENCE-001 为 `pass`；
- VAL-RELEASE-PROMOTION-001 的 source policy 和真实 promotion 记录可复现；
- GitHub settings 证据覆盖两个 Environment、三组 ruleset 和 Immutable Releases；
- 发行说明、UI 与构建配置对签名限制的描述一致；
- 任何 secret、证书、用户数据或模型权重均未进入仓库或产物日志。

repository owner、可修改 `main`/workflow 的 contents writer 与 settings 管理员仍是根信任；
GitHub Draft 无资产 CAS，verify→fixed-ID PATCH 竞态只能 post-publish 后验检测。这些真实
settings、签名构建和物理 Mac 门禁均未运行，当前仍是
**source merge GO / release NO-GO**。
