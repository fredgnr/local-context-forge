# ADR-0014：Desktop 候选构建与公开推广分离

- 状态：Accepted
- 日期：2026-07-31
- 关联需求：REQ-RELEASE-001、REQ-RELEASE-002、REQ-SECRET-001、REQ-UPDATE-001
- 依赖：ADR-0003、ADR-0011
- 细化：取代 ADR-0003 中“单一 `macos-release` Environment 承载整个 release job”的旧部署
  形态；ADR-0003 的自签名、secret 不入仓库和物理门禁决策继续有效

## 上下文

签名候选的构建成功不等于允许公开。真实 M4 安装、Gatekeeper、bundled runtime、Codex、
embedding 和跨版本更新需要在候选形成后、公开前执行，因此 tag push 必须停在 Draft。

同时，promotion 的执行代码本身也是信任对象。若从待发布 tag checkout verifier，能创建 tag
的人也能选择旧的或被削弱的 verifier。`workflow_dispatch` 因而必须固定从受保护的 `main`
启动，把 `release_tag` 仅当作要验证的资料输入；可信 `main` verifier 再把该 tag 隔离到 detached
worktree 中读取 release notes、manifest policy 和资产验证逻辑。

GitHub Draft 没有“验证这一组资产并把同一个 Release 原子发布”的 compare-and-swap（CAS）。
有 `contents: write` 的主体仍可在 verify 与 REST `PATCH` 之间修改 Draft。GitHub Immutable
Releases 能保护已公开状态，却不能消除这段 Draft 竞态。因此本决策同时使用固定 Release ID、
公开前 fresh ref/Release 复核、公开后的 attestation/immutable/资产复核来缩小并检测窗口，
但不把 Draft 描述为不可变存储。

## 决策

### 阶段一：tag-only build/sign 与 Draft

1. 只有 canonical repository 的 exact release tag push 可以进入 build/sign；触发器和
   Environment custom deployment policy 都只允许 `v*.*.*`。checkout、fresh peeled tag commit、
   `GITHUB_SHA`、版本、`main` ancestry 和 release manifest source commit 必须一致。
2. build/sign job 绑定 `macos-signing` Environment，只获得 `contents: read`，并且整个仓库只
   配置一个发布 secret：`DESKTOP_RELEASE_CREDENTIAL_BUNDLE_BASE64`。这是唯一允许引用
   `secrets.*` 的 release job slice。
3. 独立 `create_draft` job 依赖同一次 build artifact，只有 `contents: write`，不绑定任何
   Environment，也不读取 secret。它重新验证本地资产；exact tag 无 Release 时创建 Draft。
   若前次创建成功后响应或 runner 丢失而留下唯一 Draft，只能在该 Draft 与本次同 tag 重建
   候选的 tag/title/state/notes、name、size、SHA-256、asset state 和 canonical download
   URL 完整一致时恢复成功。published、重复或漂移状态全部拒绝，且绝不覆盖现有 Release。
4. tag push 到此结束。任何 tag push 路径都不得包含 `draft=false`、发布 REST `PATCH` 或等价
   公开 API。失败时不得覆盖或 `--clobber` Draft；修复必须从受保护 `main` 提升版本并创建新 tag。

### 阶段二：main-only、secret-free promotion

1. 维护者只能以 `workflow_dispatch --ref main` 启动 promotion。`GITHUB_REF`、ref type、
   `GITHUB_REF_NAME` 和 `GITHUB_SHA` 必须证明本次 verifier 来自当时的 exact `main` head。
   `release_tag` 只是现有候选的资料输入，不是 workflow/code checkout ref；还必须输入真机
   测试记录的 `release-manifest.json` 小写 SHA-256 并显式确认公开。不同 tag 的 promotion
   共用一个 `cancel-in-progress: false` concurrency group，避免相互并发发布。
2. promotion 绑定 `macos-release` Environment，其 custom deployment policy 只允许 branch
   `main`。它不依赖 build/sign job、不重新构建，并且 `macos-release` 必须是零 secret；
   promotion job slice 不得出现 `secrets.*`。
3. 可信 `main` verifier 显式 fetch 输入 tag 到私有 ref，peel 到 commit，验证它仍属于 fresh
   `origin/main` 历史，然后在全新 detached worktree 隔离 tag 内容。工作流脚本来自可信
   `GITHUB_WORKSPACE`，但 release notes、manifest policy 和 tag-bound source 数据从隔离
   worktree 读取，不能执行 tag 中的 workflow verifier。
4. promotion 必须从 API 严格选出唯一 exact Draft，拒绝任何已 published 预状态；后者一律是
   发布安全事件，不能把重跑包装成幂等成功。它记录数值 Release ID，下载每个 remote asset
   到新空目录，验证签名、manifest、candidate digest 和完整集合。
5. 在公开前，promotion 再次 fresh-fetch 并 peel tag，重新获取 Release 列表，要求 tag、
   Draft 状态和此前固定的 Release ID 全部不变，再由可信 `main` verifier 复核 notes 和资产。
   `verifyPromotionOrder` 必须以这次 `PATCH` 前 fresh-fetched `origin/main` comparison ref
   重新计算 SemVer 顺序和 `make_latest`，不能继续使用 workflow 启动时固定的旧 HEAD；否则并行
   promotion 可能把已被新 tag 超越的旧版本设为 latest。唯一公开操作是对该固定 Release ID
   执行一次 REST `PATCH {"draft":false,"make_latest":...}`，不能按 tag 模糊选择，也不能上传、
   替换或编辑资产。
6. `PATCH` 后必须再次 fresh-fetch/peel tag，运行 `gh release verify <tag>`，重新获取同一
   Release ID，并验证 `draft=false`、`published_at`、`immutable=true`、notes 和完整资产集合。
   任一步失败均为发布安全事件：立即停止公告与 update feed，保留证据并升级处置；不得重跑
   “洗绿”、编辑既有 Release 或覆盖 tag。

### 必需的 GitHub 控制面

在首次 `--upload` 或轮换前，管理员和 bootstrap 必须共同确认：

1. `macos-signing` 与 `macos-release` 都配置 required reviewers、`prevent self review`，
   并在 GitHub UI 关闭 “Allow administrators to bypass configured protection rules”。
   前者只允许 tag `v*.*.*`，且只有唯一 credential bundle secret；后者只允许 branch
   `main`，且 secret 集合为空。
2. active repository branch ruleset `protected-main` 精确包含 `refs/heads/main`，无 bypass
   actor，要求 pull request、至少一名独立 approval、push 后 dismiss stale approvals、
   last-push approval、全部 review threads resolved，并禁止 force push 和 deletion。
3. active tag ruleset `release-tag-creation` 精确包含 `refs/tags/v*.*.*`，用 creation rule
   阻止普通主体创建 release tag；唯一 bypass actor 是 canonical repository owner user，
   仅用于创建 tag。
4. active tag ruleset `immutable-release-tags` 对相同 pattern 禁止 update 和 deletion，且没有
   bypass actor。release tag 一经创建不能移动或删除。
5. GitHub Immutable Releases 必须开启，使 published Release 及其资产在公开后不可修改。

bootstrap 对可由 API 确认的 repository、Environment、ruleset、secret membership 和
Immutable Releases 配置 fail closed；由于 admin bypass 开关的 REST 表现不可靠，`--upload`
还必须要求操作者在 UI 核对后显式传入 `--confirm-admin-bypass-disabled`。这些检查的源码合同
不是仓库真实设置已正确配置的证据。

### 根信任与证据边界

1. repository owner、能改写 `main`/workflow 的 `contents` writer 和能改 GitHub 设置的管理员
   仍是根信任。ruleset、reviewer、owner-only tag creation 和 immutable publication 缩小权限
   与误操作面，不会把恶意 owner/writer 变成不可信主体。
2. Draft 只代表“可供验证的候选”，不是推荐下载、一般可用或 update feed 放行。
3. GitHub Draft 没有资产 CAS；verify → 固定 Release ID `PATCH` 之间的修改竞态只能由
   post-publish `gh release verify`、`immutable=true` 和完整资产重验做后验检测，不能原子预防。
4. 当前证据结论保持 **source merge GO / release NO-GO**。source policy tests 可以证明
   workflow/bootstrap 的静态合同，但真实 GitHub settings、两次 Environment 审批、真实签名
   产物、clean-user、物理 M4 和 0.0.1 → 0.0.2 均继续为 `not-run`。
5. automatic apply 继续禁用；本决策不改变 ADR-0011 的 Main-owned signed update 边界。

## 后果

正面后果：

- tag push 不再自动公开未经真机验证的 DMG；
- 签名 secret 只在 `macos-signing` 的候选构建中可用，`macos-release` 明确零 secret；
- promotion verifier 由 protected `main` 提供，待发布 tag 只作为隔离数据读取；
- owner-only tag creation、不可移动 tag、固定 Release ID 和 Immutable Releases 把身份漂移
  与公开后篡改变成 fail-closed/可检测事件；
- 真机测试摘要与最终远端候选由同一 validator 在公开前后绑定。

成本与限制：

- 正式发布需要两次独立 Environment 审批、一次显式 main-ref promotion 和完整设置维护；
- promotion 依赖 GitHub 保留 Draft 资产，不能只依赖有保留期的 Actions artifact；
- writer/owner 根信任和 Draft verify→PATCH 的无 CAS 窗口仍存在，只能在公开后检测；
- 当前 self-signed、未 notarize、未 hardened 的限制和 Gatekeeper 摩擦不变。

## 替代方案

1. **tag push 通过后立即公开。** 拒绝：无法插入物理门禁。
2. **以 tag ref 启动 promotion。** 拒绝：验证器也来自待验证 tag，不能建立 trusted-main
   policy 边界。
3. **promotion 重新签名构建。** 拒绝：真机测试字节与公开字节可能不同，并扩大 secret 暴露面。
4. **已公开且看似一致的重跑按幂等成功。** 拒绝：无法区分丢失响应与绕过 promotion 的公开；
   published 预状态必须作为安全事件。
5. **人工在 GitHub 页面点 Publish 或覆盖 Draft 资产。** 拒绝：绕过 candidate digest、固定
   Release ID、fresh ref 和完整资产复核。
6. **只开启 Immutable Releases。** 不足：它保护 published Release，不为 Draft 提供资产 CAS。

## 验证门禁

- VAL-RELEASE-POLICY-001：source tests 证明三段 job/event/权限/secret 边界、main-only
  promotion、exact tag、Draft-only push、ruleset/Environment/Immutable Releases bootstrap
  合同。
- VAL-RELEASE-PROMOTION-001：source tests 证明可信 `main` verifier、隔离 tag worktree、
  fresh peel、`PATCH` 前 fresh `origin/main` comparison ref 的 promotion order、固定 Release
  ID REST `PATCH`、published 预状态 fail closed、post-publish `gh release verify`/immutable/
  完整集合复核。
- VAL-SECRET-001：真实仓库设置证明两 Environment reviewer/self-review/admin-bypass、
  exact deployment policy、secret membership、三组 ruleset 和 Immutable Releases；当前
  仍为 `not-run`。
- VAL-RELEASE-001、VAL-INSTALL-001、VAL-UPDATE-001：真实 M4 候选、干净用户和跨版本
  证据完成前均为 `not-run`。
