# ADR-0003：macOS DMG、自签名与更新策略

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-INSTALL-001、REQ-RELEASE-001、REQ-SECRET-001、REQ-UPDATE-001

## 上下文

项目是公开仓库，目标是向 macOS Apple Silicon 用户提供一个默认 DMG。当前发行约束使用
自签名证书，不进行 Apple notarization，也不启用 hardened runtime。这意味着 Gatekeeper
体验和平台安全能力弱于 Developer ID + notarization，不能在文档或 UI 中暗示 Apple 已验证。

自更新在这种签名条件下是否可靠，必须通过真实版本跨越证明。CI 构建成功、模拟 feed 或同版本
重装都不能替代 0.0.1 → 0.0.2 的物理 Mac 测试。自动更新失败时仍需要可验证、可恢复的默认路径。

## 决策

### 发行物与签名

1. 面向用户的默认安装产物是 macOS arm64 DMG；应用、Python `onedir` 和 Node/QMD worker
   必须全部位于受控 bundle/resources 中。
2. release 使用固定自签名 code-signing 身份。所有嵌套 executable 先签，最后签 `.app`；
   记录 identity fingerprint、架构、bundle/version 和 DMG SHA-256。
3. 当前明确不 notarize、不 stapling、不启用 hardened runtime。下载页、安装说明、About/
   diagnostics 与 release notes 必须一致披露该限制和可能的 Gatekeeper 操作。
4. 不通过禁用 Gatekeeper、移除 quarantine 或要求 `sudo` 来“修复”安装。用户可选择是否继续，
   失败时提供可撤销说明。

### 公开仓库与 secrets

1. release job 必须绑定受保护 GitHub Environment `macos-release`，使用 environment reviewer、
   tag/branch policy 和最小权限。
2. 自签名证书/密码及更新元数据私钥只存为该 Environment Secrets；不得放在仓库、普通
   Actions secrets、artifact、cache、日志或 fork/PR job。
3. pull request、fork、普通 CI 和非 release 手动任务只构建 unsigned/ad-hoc 测试产物，
   不得获得 release secrets 或发布权限。
4. release 输入固定为受保护 commit/tag，job 权限显式声明。发布前验证工作树来源、版本单调性、
   依赖锁、产物清单和签名结果。

### 更新与 fallback

1. 应用固定更新源与内置更新公钥。下载的 metadata 和 artifact 必须在激活/打开前通过发布者
   签名、版本/架构约束和 digest 验证；HTTPS 不是唯一完整性依据。
2. 自动应用更新在 `VAL-UPDATE-001` 通过前不是可交付能力。可以检查更新，但默认走下述
   DMG fallback，或在测试通道中试验自动应用。
3. 必须在物理 Apple Silicon Mac 上从已安装、自签名 0.0.1 创建真实用户数据，再通过发布 feed
   更新至 0.0.2，重启并验证版本、code identity、sidecars、数据和 rollback diagnostics。
4. 同一门禁必须注入自动更新失败。应用随后自动下载经过验证的 0.0.2 DMG 到受控临时下载位置，
   调用系统打开 DMG，并向用户说明拖拽替换步骤；不得静默执行安装器、删除当前 app 或清除数据。
5. 自动更新在任何 release 上失败时均回退到该下载并打开 DMG 路径。验证失败则删除/隔离
   partial artifact，不打开文件，只显示重试和手动 release 页。
6. 更新安装前停止 sidecars、flush 状态并记录当前版本；数据 schema 不可逆升级需要独立迁移/
   rollback 门禁。

当前实现边界不改写上述未来物理门禁：在 automatic apply 尚未设计或通过门禁时，signed
check/download 和用户确认后的 verified DMG open 均 fail closed；source/unprovisioned、
校验或网络错误不会自动下载或打开旁路资产。用户只能通过显式操作让 Main 打开固定 canonical
Release 页面，renderer 无 URL，该操作也不改变 signed updater 状态。真实 fallback/download/
open、protected Release 与 0.0.1 → 0.0.2 仍是 `not-run`。

## 后果

正面后果：

- 用户获得单一默认 DMG 和无外部运行时的安装路径；
- public fork/PR 无法借 release 流程读取签名材料；
- 自动更新的可用性由真实版本跨越而不是配置推断；
- 即使自动应用失败，仍有校验后的 DMG 恢复路径。

成本与限制：

- 自签名无法提供 Developer ID/notarization 的 Apple 信任，首次安装摩擦更高；
- 无 hardened runtime 降低平台加固，并可能限制 updater 行为；
- 需要维护发布者签名密钥、轮换/撤销流程和实机门禁；
- fallback 仍需要用户替换应用，不能称为无人值守更新。

## 替代方案

1. **Developer ID + notarization + hardened runtime。** 当前约束不采用；未来采用时必须新增 ADR
   并重跑全部发行/更新门禁。
2. **只发布 ZIP。** 拒绝：DMG 是默认用户体验；updater 内部辅助 artifact 不改变该默认。
3. **把证书放 repository secret。** 拒绝：缺少受保护 environment 审批和范围隔离。
4. **首次发布即默认自动 apply。** 拒绝：未经 0.0.1 → 0.0.2 实机证明。
5. **失败后只打开浏览器 release 页。** 不足：要求自动下载并打开已验证 DMG；release 页仅是
   下载/验证也失败后的人工出口。
6. **关闭 Gatekeeper 或清除 quarantine。** 拒绝：削弱用户系统安全。

## 验证门禁

- VAL-INSTALL-001：干净 Apple Silicon Mac 从 DMG 安装并运行，不借 Docker/Homebrew/
  Python/Node/Git/ctags。
- VAL-RELEASE-001：验证 arm64、nested signing order、最终 code identity、DMG digest、
  SBOM/许可证清单和限制披露一致。
- VAL-SECRET-001：证明 fork PR、普通 CI、未授权 tag 和未获 Environment approval 的 job
  不能读取 secrets 或发布。
- VAL-UPDATE-001：物理 0.0.1 → 0.0.2 自动路径与失败注入 fallback 均通过，并保留数据。

以上门禁当前尚未运行；自动应用更新因此仍是计划能力。
