# ITER-0004：macOS release foundation

- 状态：`planned`
- 依赖：ITER-0001–0003 的门禁通过
- 路线图阶段：P5

## 目标与范围

交付 macOS Apple Silicon arm64 DMG。build/sign 只由 `v*.*.*` tag push 进入
`macos-signing`，该 Environment 保存仓库唯一 credential bundle secret；Draft job 不绑定
Environment/secret。公开必须在真机测试后由 `workflow_dispatch --ref main` 进入 branch-only、
zero-secret `macos-release`，以 `release_tag` 作为资料输入，由 trusted `main` verifier 对隔离
tag worktree 和 fixed Release ID 完成。明确披露不 notarize、不启用 hardened runtime。

## 计划任务

- [ ] P01 建立 arm64 DMG/ZIP 构建、资源清单、版本和摘要产物。
- [ ] P02 配置两个受保护 Environment：都 required reviewers、prevent self review、UI 禁
  admin bypass；`macos-signing` 只允许 tag `v*.*.*`/唯一 secret，`macos-release` 只允许
  branch `main`/零 secret。
- [ ] P02a 配置 active `protected-main`（PR、独立 approval、dismiss stale、last-push
  approval、resolve threads、no force/delete、no bypass）、owner-only
  `release-tag-creation`、no-bypass `immutable-release-tags`，并开启 GitHub Immutable
  Releases。
- [ ] P03 在授权 job 内临时导入证书，发布后清理临时 keychain。
- [ ] P04 验证 PR、fork 和普通 CI 均无法读取发布秘密。
- [ ] P05 在无外部运行时的干净 Apple Silicon Mac 完成安装 smoke。
- [ ] P06 从同一 Draft 下载物理测试候选，记录 `release-manifest.json` SHA-256，经第二次
  Environment 审批；以 `--ref main` 启动 trusted verifier，隔离/fresh-peel tag，固定 Release
  ID；在 `PATCH` 前以 fresh `origin/main` comparison ref 验证 promotion order/`make_latest`，
  再执行 REST `PATCH`、post-publish `gh release verify`、immutable 和完整资产复核。
- [ ] P07 演练 published 预状态、tag/Release ID/asset 漂移和 post-publish mismatch 均按发布
  安全事件 fail closed，不能重跑幂等洗绿。

## 退出门禁

- VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001 为 `pass`；
- VAL-RELEASE-PROMOTION-001 的 source policy 和真实 promotion 记录可复现；
- GitHub settings 证据覆盖两个 Environment、三组 ruleset 和 Immutable Releases；
- 发行说明、UI 与构建配置对签名限制的描述一致；
- 任何 secret、证书、用户数据或模型权重均未进入仓库或产物日志。

repository owner、可修改 `main`/workflow 的 contents writer 与 settings 管理员仍是根信任；
GitHub Draft 无资产 CAS，verify→fixed-ID PATCH 竞态只能 post-publish 后验检测。这些真实
settings、签名构建和物理 Mac 门禁均未运行，当前仍是
**source merge GO / release NO-GO**。
