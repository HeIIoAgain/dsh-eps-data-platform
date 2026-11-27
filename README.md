# dsh-eps-data-platform

从 [EPS 数据平台](https://olap.epsnet.com.cn) 取数的 DeepSeek Harness 技能 + 命令行客户端：
把网页上「登录 → 选库 → 挑指标 → 查数 → 导表」这一串点击，变成一条可以重复执行的命令。

[![CI](https://github.com/HeIIoAgain/dsh-eps-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/HeIIoAgain/dsh-eps-data-platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![DSH Skill](https://img.shields.io/badge/deepseek--harness-skill-8b5cf6.svg)](https://github.com/deepseek-ai/deepseek-harness)

[English](README.en.md) | 简体中文

---

## 它解决什么问题

你要的是「2000–2024 年各省 GDP」这样一张表，但 EPS 网页版只给你一套点选框：
先选库，再在几百个指标里找叶子节点，再勾年份，再挑布局，最后导出一份排版过的 xlsx。
下个月同样的活，得从头再点一遍。

这个技能把同一套操作编码化：Agent 记住「库 → 维度 → 成员代码」的路径，下次说一句话就能重跑；
不需要 Agent 的人，也可以直接 `eps-client query` 拿一份干净的 CSV / Excel 给 pandas 或 Stata 用。

它的**边界**（来自平台规则，不是实现偷懒）：

- **登录只走手机短信验证码**，且验证码必须由你本人在网页上点「获取验证码」后收到 —— 发码接口前置了
  阿里云滑块验证码，本项目不自动化、不绕过；
- **只能取你账号已订阅的库**，未开通的库直接报「无权限」，没有绕过的路径；
- **有频控**：连续查询会返回「操作过于频繁」，需等待约 1 分钟；单次查询约 5000 格上限，
  超出要拆，拆的时候要克制（见下方「频控」）；
- **有下载配额**：本账号口径 200 次/日，且只有 `download`（平台原生导出）消耗次数，
  `query` 导出 CSV/Excel 不消耗。

## 特性

- **一个文件就是全部实现**：`scripts/eps_client.py` 不依赖任何 EPS SDK，只有 `requests` + `cryptography`
- **解密前端密文**：复刻 `dataletBO` 的 CryptoJS/AES 派生，所以维度树、成员代码都能直接读
- **代码是长码，脚本帮你找**：`dims` / `dimtree` 会把 `891` 的指标树展开，标出 `[数据]`（能查）
  与 `[目录]`（只是分类，查不出数）
- **导出即成品**：宽表 CSV（`utf-8-sig`，Excel 双击不乱码）+ 长表 CSV（pandas 直接用）+ Excel 双 sheet，
  数值写成真数字而不是文本 ← 这一步决定了后面能不能直接算
- **配额可见**：`quota` 先做一次最小查询再读配额，**不消耗**下载次数
- **频控兜底**：`RATE_LIMITED` 指数退避重试，默认请求间隔 0.8s
- **凭据只在本机**：`sid` 存 `~/.eps_sid`（权限 600），不进仓库、不进日志、不进聊天记录

## 安装

### 方式一：作为 DSH 技能（推荐）

`SKILL.md` 在仓库根目录，所以克隆到技能目录即可，不需要复制文件：

```bash
git clone https://github.com/HeIIoAgain/dsh-eps-data-platform.git \
  ~/.dsh/skills/eps-data-platform
pip install requests cryptography openpyxl
```

```powershell
# Windows PowerShell
git clone https://github.com/HeIIoAgain/dsh-eps-data-platform.git "$env:USERPROFILE\.dsh\skills\eps-data-platform"
pip install requests cryptography openpyxl
```

> 技能根目录默认是 `~/.dsh/skills`（可用 `$DSH_HOME` 覆盖）。重启 DSH 或新开一个会话后，
> 技能列表里会出现 `eps-data-platform`，之后用自然语言触发即可。

### 方式二：只装命令行（不需要 DSH）

```bash
pip install "git+https://github.com/HeIIoAgain/dsh-eps-data-platform.git"
eps-client --help
```

装出的是 `eps-client` 命令；也可以不安装，直接 `python scripts/eps_client.py ...`。

`--xlsx` 导出需要 `openpyxl`（`pip install "eps-data-platform[excel]"` 或
`pip install openpyxl`）；不装也能用 CSV。

## 用法

四步：登录一次 → 找库 → 找指标代码 → 取数。

### 1) 登录（唯一需要人工的一步）

先在 <https://olap.epsnet.com.cn> 选「手机验证码登录」，填手机号、点「获取验证码」（有滑块就拖一下），
然后把收到的 6 位码交给脚本：

```bash
eps-client login --account 13800000000 --code 123456
```

`sid` 落到 `~/.eps_sid`（权限 600），后续命令自动复用。**它是你账号的会话凭证，别外传。**

### 2) 找库（免登录）

```bash
$ eps-client tree
  130000  宏观经济  (pid=0, total=35597805)
  150000  产业经济  (pid=0, total=None)
  160000  贸易外经  (pid=0, total=None)
  120000  上市公司  (pid=0, total=70794433)
  ...
```

```bash
$ eps-client cubes --filter 中国宏观经济数据库
# 13 个库
  cubeId  名称                     全名                                       更新时间
       9  中国宏观经济数据库              中国宏观经济数据库                                2026-11-12
     891  年度（全国）                 中国宏观经济数据库 - 年度（全国）                       2026-11-12
     892  年度（分省级）                中国宏观经济数据库 - 年度（分省级）                      2026-11-12
     900  年度（分省分行业）              中国宏观经济数据库 - 年度（分省分行业）                    2026-10-30
```

`folderType=1` 的才是能查的数据表，`891` 是常用的「年度（全国）」。

### 3) 找指标代码

```bash
eps-client dims --cube 891                       # 布局 + 各维度顶层成员
eps-client dimtree --cube 891 --dim indicator --parent 0101 --depth 3
```

```
  01010103  国内生产总值(亿元)                      [数据]
  01010104  ...
```

代码是**长码**：2024 年是 `2024010101`，GDP 是 `01010103`。原样用树里给出的 `dimCode`，
不要按「2024」「GDP」这种直觉去猜。

### 4) 取数

```bash
eps-client query --cube 891 \
  --dims '{"time":["2024010101","2023010101"],"indicator":["01010103"]}' \
  --out gdp.csv --long gdp_long.csv --xlsx gdp.xlsx
```

```
[i] cube=891 sheetId=**** 布局: 行=time 列=indicator 固定=
[i] 返回 2 行 x 2 列, dataCount=2
已写入宽表: gdp.csv
已写入长表: gdp_long.csv
已写入 Excel: gdp.xlsx
```

`gdp.csv`（宽表，和网页上看到的一样；下面是**示意**，数值以平台返回为准）：

```csv
,国内生产总值(亿元)
2024年,<数值>
2023年,<数值>
```

`gdp_long.csv`（长表，一行一个观测）：

```csv
时间,column,value
2024年,国内生产总值(亿元),<数值>
2023年,国内生产总值(亿元),<数值>
```

一次查询可以同时放多个指标 × 多个年份 —— **能一次查完就不要拆**，拆要多等 60 秒频控。

### 在 DSH 里用自然语言

> 用 eps-data-platform 技能登录 EPS，我的手机号是 138xxxxxxxx

> 帮我取 2015–2024 年全国 GDP 和人均 GDP，导成 Excel

Agent 会读 `SKILL.md` 的步骤，自己调 `dims` / `dimtree` 找代码、拼 `dims`、导出，并在报错时按
「排错表」处理（重新登录、等 60s、换 `[数据]` 代码）。

### 查下载额度（不消耗次数）

```bash
eps-client quota --cube 891
```

### 下载平台原生文件（消耗次数）

```bash
eps-client download --cube 891 \
  --dims '{"time":["2024010101"],"indicator":["01010103"]}' \
  --out gdp.xlsx --export-type XLSX
```

只有需要平台自带的多 sheet 排版 / PDF / Stata 格式时才用它。**会扣账号的每日下载次数**，
没被明确要求就别跑。

## 配置 / 退出码 / 环境变量

| 项 | 默认 | 说明 |
|---|---|---|
| `~/.eps_sid` | — | `login` 写入的会话文件（600）；删掉即退出登录 |
| `EPS_SID` | 空 | 用环境变量直接给 `sid`，优先于文件 |
| `EPS_SID_FILE` | `~/.eps_sid` | 自定义 sid 文件位置 |
| `--sid` | 空 | 单次命令指定 sid |
| `--timeout` | `600` | 单请求超时（秒）；下载大文件时调大 |
| `--debug` | 关 | 打印每个请求，排错用 |
| `--lang` | `1` | `1` 中文 / `2` 英文 |

| 退出码 | 含义 |
|---|---|
| `0` | 成功 |
| `2` | 接口错误：未登录 / sid 过期 / 无权限 / 频控 / 无数据；也是参数用法错误的退出码 |
| `3` | 网络错误（连不上、超时、代理问题） |

代理走 `requests` 的标准行为，`HTTPS_PROXY` / `NO_PROXY` 环境变量有效。

## 排错

| 现象 | 处理 |
|---|---|
| `请登录后重试` / `登录已过期` | sid 失效 → 重新 `login` |
| `操作过于频繁，请稍候。` | 频控 → 等 60s，并把多次查询合并成一次 |
| 查询返回空 / `暂无数据` | 用了 `[目录]` 节点，或该库没有这个维度 → 用 `dimtree` 换 `[数据]` 代码 |
| `验证码错误` / `请先获取验证码` | 码过期（几分钟）→ 重新点「获取验证码」 |
| `您的账号下载次数已达到今日上限` | 当天 `download` 额度用完 → 次日再用；`query` 导 CSV 不占额度 |
| 解密报错 | 前端加密常量可能改了 → 见 `references/api-map.md` 的更新方法 |

更多细节见 [`references/api-map.md`](references/api-map.md)（接口清单、加密细节、实测记录）与
[`references/tutorial.md`](references/tutorial.md)（完整教程，含不装 DSH 时直接调 HTTP API 的写法）。

## 平台支持

| 系统 | 状态 |
|---|---|
| Windows 10/11 | ✅ |
| macOS | ✅ |
| Linux | ✅ |

Python 3.10 / 3.11 / 3.12（CI 三个版本都跑）。纯 HTTP 客户端，无浏览器依赖。

## 目录结构

```text
dsh-eps-data-platform/
├── SKILL.md                  # DSH 技能说明（操作手册 + 排错表 + 合规红线）
├── scripts/eps_client.py     # 全部实现：登录/目录/维度/取数/导出/限速重试
├── references/
│   ├── api-map.md            # 接口清单、请求/响应形状、加密细节
│   └── tutorial.md           # 完整教程（含纯 HTTP 用法）
├── tests/                    # 离线测试（不联网、不需要账号）
├── pyproject.toml
└── .github/workflows/ci.yml
```

## 合规与免责

- 仅在你本人或所在机构**拥有合法访问权限**的账号下使用；
- 不绕过登录、订阅、下载次数、验证码等任何平台风控；
- 不用于全库扫描、高频轮询或转卖数据；
- 引用数据时保留来源：**EPS 数据平台 + 库名 + 指标代码**；数值以平台返回为准；
- 本项目是非官方客户端，与北京福卡斯特 / EPS 数据平台无隶属关系，平台接口变更可能导致失效。

## License

[MIT](LICENSE) © 2026 HeIIoAgain
