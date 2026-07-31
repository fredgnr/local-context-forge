# ADR-0009：内置运行时的固定来源、清单与 fail-closed 打包

- 状态：Accepted
- 日期：2026-07-30
- 关联需求：REQ-PY-001、REQ-QMD-001、REQ-INSTALL-001、REQ-CI-001
- 部分取代：ADR-0001 中固定 Python 3.12 的版本条款
- 后续决策：第 4 条中的 lexical-only/no-model-download 范围由
  [ADR-0010](0010-qmd-local-embedding-profile.md) 部分取代

## 上下文

PyInstaller `onedir`、Node/QMD 和 native addon 只有在来源、架构、依赖闭包和 app resources
完全一致时，才能证明目标机不借用系统运行时。原计划的 CPython 3.12.13 在官方
`actions/python-versions` release 中没有 Darwin arm64 产物，继续固定该版本会使 M4 打包
必然失败。仅把版本或 SHA 写入环境变量也不是实际校验。

## 决策

1. Python bundled runtime 固定为 CPython 3.13.14，来源 tag
   `3.13.14-27320626148`、archive
   `python-3.13.14-darwin-arm64.tar.gz`、SHA-256
   `839b14df8a24415e17d15f222e2ac01d3a90845deb39df642e2cc01869140a34`；
   `hashes.sha256` 自身固定为
   `b4dd388b14ff20ced93003e31e2be8d486049456161fc1ea393aa7c64a000e17`。
2. CI 实际下载 archive 与 hash manifest，分别验证固定摘要，并验证 manifest 中 archive
   条目一致。构建必须使用该解包树的 Python，并检查 `sys.executable/base_prefix` 位于
   声明 install root；不得把未使用的环境变量称为 provenance。
3. Python 以 PyInstaller `onedir` 交付；构建工具和 wheel 使用 hash lock。manifest 记录
   产品/协议/数据库 schema、toolchain、runner image、source commit、输入 digest、
   组件/许可证、SBOM、精确文件 inventory、Mach-O 架构/dylib/RPATH 和 normalized digest。
4. Node 固定 22.23.2、arm64 和对应 ABI；QMD 固定 2.5.3。production dependencies 先
   `--ignore-scripts` 安装，再显式从源码 rebuild `better-sqlite3`，审计所有 `.node` 和
   动态库。P2 lexical runtime 不安装/下载 embedding 模型。
5. Python 和 QMD staging 均使用 canonical JSON manifest 与独立 SHA-256 文件。
   `beforePack` 重新计算 inventory、normalized digest、关键输入 digest、版本/schema、
   commit 和目标架构；任一不一致则 fail closed。
6. Electron builder 只能复制已审计 staging，不能在打包时隐式下载或构建。生成目录、
   private evidence 和运行时 archive 不入库；lock、schema、policy、notices 模板和构建脚本
   入库。
7. macOS arm64 Actions 生成 L3 之前的 packaging evidence，但不能替代 clean-user DMG
   门禁。workflow 固定 action commit、最小权限、无 release secret；记录 runner image
   版本而不伪称可永久固定 GitHub runner 镜像。
8. frozen smoke 在故意失败的 `PATH` 下执行 version、doctor、真实 UDS handshake/health
   和领域回归；任何产品调用系统 Python、Node、Git、qmd 或 ctags 都使门禁失败。

## 后果

- M4 构建使用实际存在且可验证的官方 arm64 Python 产物；
- 每个 packaged resource 可追到输入、版本、许可证和 native closure；
- 构建与审计时间增加，macOS/native 门禁不能在普通 Linux source test 中伪造；
- 未来升级 Python、Node、QMD、PyInstaller 或 native ABI 都必须更新 lock、manifest 和证据。

## 替代方案

1. **降级到仍有 arm64 产物的旧 Python 3.12 patch。** 拒绝：引入不必要的安全回退。
2. **使用 runner 预装 Python。** 拒绝：来源与缓存不可独立复核。
3. **electron-builder 打包时在线安装依赖。** 拒绝：产物内容不可预测。
4. **只检查版本字符串。** 拒绝：不能证明 bytes、架构或动态库闭包。

## 验证门禁

- VAL-PY-001：来源双重摘要、hash-locked 构建、manifest/schema、Mach-O、许可证/SBOM、
  tamper rejection、frozen UDS/domain 和 PATH trap。
- VAL-QMD-001：Node/QMD/integrity、better-sqlite3 arm64 ABI、manifest、离线 lexical
  生命周期和 PATH/model/network trap。
- VAL-PACK-001：`beforePack` 接受精确 staging，并拒绝 payload、manifest、schema、commit、
  inventory、normalized digest、architecture 或 input digest 的任一篡改。
