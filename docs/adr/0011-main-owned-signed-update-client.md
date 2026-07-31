# ADR-0011：Main-owned signed update client

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-TRUST-001、REQ-RELEASE-001、REQ-UPDATE-001
- 依赖：ADR-0001、ADR-0003、ADR-0009

## 上下文

ADR-0003 要求桌面发布使用受保护的 macOS 构建和独立更新信任材料，并在自动更新实机门禁
失败时提供“校验后下载并打开 DMG”的恢复路径。GitHub HTTPS、release 页面、
`<channel>-mac.yml`、资产文件名和 renderer 中显示的更新状态都不是足够的信任锚。重定向、
JSON/YAML 解析、签名验证、分块下载、缓存复用和 IPC 暴露均位于攻击面内。

当前还没有通过受保护发布 Environment 生成的生产更新公钥，也没有 0.0.1 → 0.0.2
物理 Mac 证据。因此实现只能提供 fail-closed 的签名检查与用户确认后的 DMG fallback，
不能宣称自动应用更新。

## 决策

1. 更新检查和下载只由 Electron Main 执行。仓库、channel、架构、manifest 名称和
   GitHub API 路由在应用内固定；renderer 不能提供 URL、路径、header、key、signature、
   asset 名称或命令参数。
2. source/unpackaged、非 `darwin/arm64` 或尚未配置生产信任材料的构建把 signed 更新能力
   报告为 `unavailable`，且不发起更新网络请求。独立的手动后备只在用户显式操作后让 Main
   打开编译期固定的 canonical GitHub Releases 页面；renderer 不提供也不读取 URL。
3. bundle 内携带独立 Ed25519 更新公钥和锁文件。受保护发布构建必须使用已配置 generation
   与 digest；`beforePack` 对缺失、占位、格式错误、锁不匹配或非预期权限 fail closed。
   macOS 代码签名身份不能代替更新 manifest 的独立签名。
4. 权威 manifest 是 canonical JSON，使用 exact schema，固定 repository、version、
   channel、arch，并列出完整发布资产集合的名称、大小和 SHA-256。任何额外/缺失字段、
   重复项、非规范编码、范围外数值或签名失败都拒绝。`<channel>-mac.yml` 和 ZIP 既不作为
   信任输入，也不由此客户端执行。
5. 网络只访问固定 GitHub API/release host 和预期 path/query。每次有限重定向都重新验证
   scheme、host、port、path 和 query；不携带凭据；响应头、manifest 和 asset 均有上限。
6. 下载写入应用私有 update cache。临时文件使用排他、`O_NOFOLLOW` 创建，并验证 owner、
   mode、link count 和 regular-file 身份；内容流式限制大小并计算 SHA-256，`fsync` 后原子
   rename。复用缓存和调用系统打开前都重新验证身份、大小和 digest；失败/取消清理 partial。
7. Main 只暴露无参数、类型化 IPC，返回有限状态、进度和稳定错误枚举。不得向 renderer
   返回 URL、文件路径、公钥、签名、响应 header、原始解析错误或 native stderr。
   check/download/open/manual-release-page 单飞串行，shutdown 取消在途操作。
8. signed 资产路径唯一可打开的是经上述验证且由用户明确操作触发的 DMG。source/
   unprovisioned、signature/schema/asset/cache/digest 或网络失败不会自动打开页面或下载旁路
   资产；用户可另行显式打开固定 Release 页面。该外部页面操作失败只返回稳定错误，不改写
   signed updater 的 candidate/error 状态。
9. Main 不静默安装、mount、执行 installer、打开 ZIP、自动重启、删除现有应用或自动 apply。
   自动应用更新必须等 `VAL-UPDATE-001` 通过，并通过新增或 superseding ADR 明确其信任和
   恢复语义。

## 后果

- source build 和未配置生产公钥的包不会误触公开 release feed；
- 被篡改的 release metadata、asset、缓存文件或重定向会在 Main 边界 fail closed；
- renderer 只能驱动有限状态机，不能把更新客户端变成任意网络、文件或进程代理；
- 在 provisioned packaged build 已发现合法候选时，用户可显式下载并打开已独立签名、
  hash 校验的 DMG；
- signed 路径不可用时用户仍有固定 Release 页面出口，但它不证明页面存在 Release、DMG
  经过验证或 automatic apply 可用；
- 该决策不证明 protected release、Gatekeeper、真实下载或跨版本更新已完成。

## 替代方案

1. **直接信任 `<channel>-mac.yml` 或 GitHub HTTPS。** 拒绝：两者没有把资产集合、更新 channel
   与应用内独立信任锚绑定。
2. **在 renderer 中下载或验签。** 拒绝：renderer 是不可信展示层，且不应获得网络、路径
   或密钥材料。
3. **只依赖 macOS 代码签名。** 拒绝：下载前无法验证 manifest/asset 绑定，且本项目当前
   自签名、未 notarize。
4. **现在启用 electron-updater 自动 apply。** 拒绝：真实签名 feed、保护环境和物理
   0.0.1 → 0.0.2 门禁均未执行。
5. **让用户粘贴任意 manifest URL 或公钥。** 拒绝：会扩大 SSRF、降级和社会工程攻击面。

## 验证门禁

- VAL-UPDATE-CLIENT-001：Main/preload/Web source tests 覆盖 exact schema/signature、
  channel/arch/version、重定向和响应上限、partial/cache、owner/mode/symlink/hardlink/hash、
  打开前重验、固定 Release 页面 no-payload/URL 隐藏/状态不污染、IPC 脱敏、串行/取消和 UI
  自动 apply 禁用。
- VAL-TRUST-001：packaged app 权限审计必须证明 renderer 无 URL/path/key/signature/原始
  updater 输出；当前 packaged 子门禁保持 `not-run`。
- VAL-UPDATE-001：在物理 Apple Silicon Mac 用真实受保护发布完成 0.0.1 → 0.0.2、
  数据保留、失败注入和经验证 DMG fallback；当前保持 `not-run`，因此自动 apply 不可用。
