# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与
[语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-11-27

首个公开版本。全部能力都在真实账号上跑通过（短信验证码登录 → `center.do` 取到国家统计局口径的
GDP 数据），不是按文档猜的。

### Added

- **DSH 技能**（`SKILL.md`）：把「登录 → 选库 → 找指标 → 查询 → 导出」拆成可重复的步骤，
  Agent 按需调用；含排错表与合规红线。
- **命令行客户端**（`scripts/eps_client.py`）：
  - `login`：短信验证码登录（`loginType=MOBILE`），`sid` 存 `~/.eps_sid`（600）
  - `whoami`：校验 sid、机构与库权限
  - `tree` / `cubes`：9 个研究系列、900+ 个库（免登录），支持关键字过滤
  - `dims` / `dimtree`：维度布局、成员代码树，区分 `[数据]` 与 `[目录]` 节点
  - `quota`：每日下载次数 / 今日已用 / 单次上限（不消耗下载次数）
  - `query`：宽表 CSV + 长表 CSV + Excel（宽表/长表两个 sheet，数值为真数字）+ 原始 JSON
  - `download`：平台原生导出（xlsx/xls/csv/pdf/dta/txt），会消耗下载次数，需显式调用
- **加密兼容层**：复刻前端 `Ke.decrypt`（CryptoJS passphrase → AES-128-CBC/PKCS7），
  解开 `getDimension.do` 等接口的 `dataletBO` 密文；派生常量有测试守护。
- **频控兜底**：`RATE_LIMITED` 指数退避重试 + 默认 0.8s 请求间隔。
- **接口地图**（`references/api-map.md`）：路径、参数、响应形状、加密细节与实测记录。
- **完整教程**（`references/tutorial.md`）：自然语言用法 + 不用 DSH 时直接调 HTTP API 的写法。

### Notes

- 登录只走手机短信验证码，不自动化发码、不绕过滑块验证码、不借用 cookie。
- 只在账号订阅范围内取数；不提供全库扫描或绕过下载次数限制的能力。
