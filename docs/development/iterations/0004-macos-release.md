# ITER-0004：macOS release foundation

- 状态：`planned`
- 依赖：ITER-0001–0003 的门禁通过
- 路线图阶段：P5

## 目标与范围

交付 macOS Apple Silicon arm64 DMG，并在公开仓库中使用受保护的 `macos-release`
Environment Secrets 完成自签名发布。明确披露不 notarize、不启用 hardened runtime。

## 计划任务

- [ ] P01 建立 arm64 DMG/ZIP 构建、资源清单、版本和摘要产物。
- [ ] P02 配置受保护 Environment、审批人、tag/ref 限制和最小权限。
- [ ] P03 在授权 job 内临时导入证书，发布后清理临时 keychain。
- [ ] P04 验证 PR、fork 和普通 CI 均无法读取发布秘密。
- [ ] P05 在无外部运行时的干净 Apple Silicon Mac 完成安装 smoke。

## 退出门禁

- VAL-INSTALL-001、VAL-RELEASE-001、VAL-SECRET-001 为 `pass`；
- 发行说明、UI 与构建配置对签名限制的描述一致；
- 任何 secret、证书、用户数据或模型权重均未进入仓库或产物日志。
