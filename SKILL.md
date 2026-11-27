---
name: eps-data-platform
description: Use when the user wants data from EPS数据平台 (https://olap.epsnet.com.cn) — China macro / industry / regional / listed-company statistics — through its web API. Covers SMS-code login (loginType=MOBILE), cube (库) discovery, dimension/member-code lookup, AES decryption of encrypted dimension payloads, center.do queries, tidy CSV/Excel export, and recurring/batch pulls. Also covers diagnosing the platform's standard errors (请登录后重试 / 验证码错误 / 操作过于频繁 / 登录已过期).
whenToUse: 用户要"从 EPS / olap.epsnet.com.cn / 数据平台 取数、下数据、按指标+年份导表"，要批量导出、定时更新，或取数接口报错（请登录后重试、操作过于频繁、登录已过期、验证码错误）需要排查时。
---

# EPS 数据平台取数（olap.epsnet.com.cn）

把"登录 → 选库/指标 → 查询 → 导出"这套网页操作拆成可脚本化的 API 调用。
本文件是**操作手册**；接口清单/加密细节在 `references/api-map.md`；实现代码在
`scripts/eps_client.py`。所有结论都在真实账号上跑通过（2026-11，短信验证码登录 +
`center.do` 取到国家统计局口径的 GDP 数据），不是猜的。

## 30 秒跑通

```bash
SKILL_DIR=~/.dsh/skills/eps-data-platform     # 用 skill 工具时它会给出真实路径
CLI=$SKILL_DIR/scripts/eps_client.py
pip3 install --break-system-packages --user requests cryptography openpyxl 2>/dev/null

# 1) 登录：先向用户要手机号，让他在网页点“获取验证码”，再把 6 位码给你
python3 $CLI login --account 13800000000 --code 123456

# 2) 找库（不用登录）：folderType=1 才是能查的数据表
python3 $CLI tree
python3 $CLI cubes --filter 宏观经济

# 3) 看布局、找指标代码
python3 $CLI dims --cube 891
python3 $CLI dimtree --cube 891 --dim indicator --parent 0101 --depth 3

# 4) 取数并导出
python3 $CLI query --cube 891 \
  --dims '{"time":["2024010101","2023010101"],"indicator":["01010103"]}' \
  --out gdp.csv --long gdp_long.csv --xlsx gdp.xlsx
```

`sid` 会存到 `~/.eps_sid`（权限 600），后续命令自动复用。它是账号的会话凭证，
**不要把它打印到聊天里、不要提交进仓库**；用户要求清理时删掉该文件。

## 铁律：登录只走短信验证码

用户明确要求只用**手机短信验证码**登录，这条必须遵守：

1. 不要尝试密码、机构账号、IP 授权、CARSI、cookie 借用等其它登录方式，即使接口存在。
2. 不要自己调发码接口 `/user/verify/getSign` + `/sendCode`，也不要想办法绕过它们的
   阿里云滑块验证码（那是平台风控，且短信有真实成本）。**验证码只能由用户本人在网页上
   点"获取验证码"后收到，再交给脚本**。
3. 标准动作：向用户要绑定手机号 → 让他在 `https://olap.epsnet.com.cn` 选"手机验证码
   登录"、填手机号、点获取验证码（有滑块就拖）→ 用户把 6 位码发来（尽快，几分钟过期）
   → `login --account <手机号> --code <验证码>`。
4. 登录接口：`GET /user/login/login?account=<手机号>&verifyCode=<码>&loginType=MOBILE`
   → `{"success":true,"sid":"...","userInfo":{...}}`。`whoami` 可确认身份和权限。
5. sid 过期（接口返回"登录已过期/请重新登录"或 `loginStatus:"fail"`）就重新走第 3 步，
   不要试图延长或伪造。

## 取数流程（核心心智模型）

### 0. 站点结构

前端是 Vite SPA，后端按前缀分服务：`/eps`（OLAP 取数/维度/下载）、`/user`（登录/用户）、
`/es`（检索）、`/cms`（帮助）、`/ruoyi`（用户中心后台）。**Swagger 公开可读**，参数有
疑问先查 `https://olap.epsnet.com.cn/eps/v2/api-docs` 和 `/user/v2/api-docs`。

### 1. 找库：`metaCube/listMetaCubeTree.do` / `listMetaCube.do`（免登录）

- `listMetaCubeTree.do`：9 个研究系列（宏观经济、产业经济、贸易外经、上市公司、普查数据、
  全球经济、省级县域、市级县域、新概念数据）。
- `listMetaCube.do?currentPage=1`：一次返回全部 900+ 个库（分页字段只是摆设）。
- **`folderType`：`0` = 目录，`1` = 真正能查询的数据表**。`getDimension`/`center.do` 的
  `cubeId` 必须是 `folderType=1` 的节点。常用：`891` 年度（全国）、`897` 月度（全国）、
  `900` 年度（分省分行业），父节点分别是 `9`（中国宏观经济数据库）和 `130000`（宏观经济）。
- 库列表字段：`cubeId / cubeNameZh / cubeFnameZh / descZh / pid / folderType / startDate / lastDate`。

### 2. 拿查询条件：`getDimension.do`（需 sid）

`GET /eps/getDimension.do?cubeId=<folderType=1的id>&sid=<sid>`（header `lang: 1`）返回：

```json
{"success":true, "dataletBO":"<AES 密文>", "visitAuth":true, "cubeAuth":true}
```

`dataletBO` 要解密（前端 `Ke.decrypt`）：**AES-128-CBC/PKCS7/base64，key = iv =
UTF-8("1321321561321321")**。这个常量由前端 JS 里写死的 `U2Fsd...` 串 + 口令
`addceffs` 经 CryptoJS passphrase 模式（AES-256 + OpenSSL EVP_BytesToKey-MD5）派生，
细节和代码见 `references/api-map.md`。解开后关键字段：

| 字段 | 含义 |
|---|---|
| `sheetId` | 本次查询的 sheet 凭证，`center.do`/下载必须用它 |
| `metaLefts` / `metaTops` / `fixeds` | 行维度 / 列维度 / 固定维度的 `codeName` |
| `allDimensions.dimensionVOList` | 维度列表：`codeName`、`dimensionId`、`objList`（顶层成员树） |
| `dimensionNameMap` | `codeName → 中文名` |
| `freqId` | 频率（1 年度、更高频依次等） |

**每次调 `getDimension.do` 都会新建一个 sheetId**；`center.do` 必须配紧邻的那个。
脚本的 `query`/`download` 都是现取现用，不要手工跨命令复用旧 sheetId。

### 3. 找成员代码：`dims` / `dimtree`

- `dims --cube 891`：打印布局 + 各维度顶层成员；`--out` 存解密后的完整 JSON。
- `dimtree --cube 891 --dim indicator --parent 0101 --depth 3`：递归展开成员树，节点标
  `[数据]`（`IS_VAL=1` 或 `isEnd=1`，能查）或 `[目录]`（只是分类，查不出数）。
- 成员接口：`GET /eps/getDimensionList.do?sheetId=&dimType=<codeName>&parentCode=<dimCode>`
  （返回加密的 `dimensionList`）；全部代码：`getDimensionAll.do`。
- **代码是长码，不是直觉短码**：`time` 的 2024 年是 `2024010101`（年）/月度是类似
  `2024120101`；`indicator` 的 GDP 是 `01010103`。原样用树里的 `dimCode`。
- 维度 `codeName` 目前见到的有 `indicator`、`time`，分省库还会有 `region` 等；以
  `dims` 输出为准。

### 4. 查询：`center.do`（需 sid）

`POST /eps/center.do?sid=<sid>`，JSON body：

```json
{
  "cubeId": 891,
  "sheetId": "<上一步的 sheetId>",
  "dims": "[{\"codeName\":\"time\",\"codes\":[\"2024010101\"]},{\"codeName\":\"indicator\",\"codes\":[\"01010103\"]}]",
  "metaColumns": "indicator",
  "metaRows": "time",
  "fix": "",
  "s1": {"dealStr": "empty"}, "s2": {"method": "", "type": ""},
  "s3": {"index8020": "", "fontStyle8020": "", "bgColor8020": ""},
  "s4": {"orderStr": "", "index": ""},
  "s5": {"dealStr": "", "showBackColor": "", "showFontStyle": ""}
}
```

规则：

- `dims` 是**字符串**（对数组再 `json.dumps` 一次），元素 `{codeName, codes:[...]}`。
- `metaColumns` = 行维度（`metaLefts`）以 `-` 连接；`metaRows` = 列维度（`metaTops`）；
  `fix` = 固定维度（`fixeds`）。每个维度必须出现在三者之一，否则报错/无数据。
- `s1..s5` 是样式/处理参数，照抄默认值即可。
- 返回 `{"success":true,"dataletBO":{...}}`，`dataletBO` 是**明文**：
  `cellBOs` 二维数组，前 `len(metaTops)` 行是表头，之后每行前 `len(metaLefts)` 格是
  行标题，其余是值；单元格是 `{"showValue":..., "cellType":"VAL"|"indicator"|"APPEND",
  "rowSpan"/"colSpan", "obj"}`，数值在 `showValue`（VAL 已保留多位小数）。
- 前端提示单次约 5000 格、账号权限可能更高；超了就拆，但**拆要少**（见频控）。

### 5. 下载配额（每日次数）

平台按**账号**限制每日下载次数，信息从 `checkDownload1.do` 的响应里读：

| 字段 | 含义 |
|---|---|
| `downloadCount` | 每日下载次数上限（本账号 **200 次/日**） |
| `todayDownloadCount` | 今日已用次数（当前 0） |
| `maxRows` / `partSize` | 单次下载最大行数 1,000,000 / 分批 50,000 |
| `overLimit` / `canDownload` | 是否超限 / 当前可否下载 |

注意：
- **`checkDownload1.do` 只是"下载前检查"，不消耗次数**（调用后 `todayDownloadCount` 不变），
  真正消耗发生在 `download.do` 真正下载时。
- 单次**查询**上限看 `userInfo.metaCubeList[].querySize`（多数库 5000 格，少数 10000/50000），
  这是"格子数"不是"次数"；查询本身没有每日次数，只有频控。
- `checkDownload1.do` 需要先有一次成功的 `center.do`（返回 `success:false, message:"暂无数据，
  请调整维度或打开联动后重试"` 表示要先查出数据），所以统一用：
  `python3 $CLI quota --cube 891`（它自动做一次最小查询再读配额，不下载、不扣次数）。
- `/eps/checkDownload.do`（旧版）返回的是单次行数限制（`downloadSize/maxDownloadSize`）；
  `/eps/getAllDownloadCount` 是**平台全站**累计下载量（1,603,423,587），不是个人配额，别误用。

### 6. 导出

- `query`：宽表 CSV（`utf-8-sig`，Excel 直接打开）+ `--long` 长表 + `--xlsx`（宽表/长表
  两个 sheet，数值是真数字）+ `--raw` 原始 JSON。
- `download`：走平台原生导出——`checkDownload1.do` 拿 `sign`，再 `download.do` 下
  xlsx/xls/csv/pdf/dta/txt。**会消耗账号的每日下载次数**，没被明确要求就别跑，跑之前
  先提醒用户。单次查询结果用 `query` 导出不消耗下载次数。

### 7. 频控（必读）

连续查几次 `center.do` 后平台会返回：

```json
{"success":false,"errorCode":"RATE_LIMITED","message":"操作过于频繁，请稍候。"}
```

大约等 1 分钟恢复。脚本对"频繁/稍候"做了指数退避重试并默认请求间隔 0.8s，但这只是
兜底；**批量取数优先"一次查完"**（一次 `center.do` 可以同时放多个指标 × 多个年份），
必须拆多次时，每次之间 `sleep 60`。抓取行为要克制，别做全库扫描。

## 常用命令速查

```bash
CLI=~/.dsh/skills/eps-data-platform/scripts/eps_client.py

python3 $CLI login --account <手机号> [--code <6位码>]   # 交互式或直传验证码
python3 $CLI whoami                                    # 验证 sid/权限/机构
python3 $CLI tree                                      # 9 个研究系列
python3 $CLI cubes --filter 关键词 [--out cubes.json]    # 900+ 库清单（免登录）
python3 $CLI quota [--cube 891]                          # 查每日下载次数/已用/单次限制
python3 $CLI dims --cube 891 [--deep] [--deep-api] [--out dims.json]
python3 $CLI dimtree --cube 891 --dim indicator --parent 0101 --depth 3 [--out tree.json]
python3 $CLI query --cube 891 --dims '<json>' --out a.csv --long a_long.csv --xlsx a.xlsx
python3 $CLI query --cube 891 --select select.json --out a.csv
python3 $CLI download --cube 891 --dims '<json>' --out a.xlsx --export-type XLSX
```

`--dims` 里某个维度写 `"*"`、或加 `--all`，表示该维度用全量代码（会很大，慎用）。
`select.json` = `{"dims": {...}, "metaColumns": [...], "metaRows": [...], "fix": [...]}`，
布局不写就按平台默认。

## 排错表

| 现象 | 原因 / 处理 |
|---|---|
| `{"success":false,"message":"请登录后重试"}` | 没 sid 或 sid 过期 → 重新短信登录 |
| `验证码错误，请重新输入！` / `请先获取验证码！` | 码过期/没发码 → 让用户重新点"获取验证码"给新码 |
| `{"errorCode":"RATE_LIMITED","message":"操作过于频繁，请稍候。"}` | 频控 → 等 60s，合并查询 |
| 查询返回空（`cellBOs` 为空/`dataCount=0`） | 用了 `[目录]` 节点、年份锁定、或该库无此维度 → 换 `[数据]` 代码；`dims` 看布局 |
| `登录已过期，请重新登录！` / `loginStatus:"fail"` | sid 过期 → 重新登录 |
| 解密报错 / `dataletBO` 解不出来 | 前端加密常量可能变了 → 重新扒 `index-*.js` 里的 `tripleAesDecrypt/addceffs` 并更新 `AES_KEY`/`AES_IV` |
| `未开通`/`无权限` | 账号没订阅该库 → 换库或让用户确认权限，不要试图绕过 |
| `您的账号下载次数已达到今日上限` | 当日下载次数用尽（本账号 200 次/日）→ 次日再用；查询/导出 CSV 不占下载次数 |
| 结果单位不对 | EPS 数值是原始计量单位（亿元、元、万人…），表头/`dimFName` 里带单位，别自己换算 |

## 合规红线

- 只在该账号/机构**授权范围内**取数；不绕过登录、订阅、下载次数、验证码。
- 不提供"批量爬全库/高频轮询/转卖数据"类支持；用户要求大规模抓取时先提示平台条款与频控。
- 不把 sid、手机号、验证码、cookie 写进示例文件、提交记录或对外分享。
- 引用数据时保留来源说明（EPS 数据平台 + 库名 + 指标代码），数值以平台返回为准。

## 文件清单

| 文件 | 用途 |
|---|---|
| `scripts/eps_client.py` | 全部实现：登录、目录、维度/树、取数、解析、CSV/Excel 导出、限速重试 |
| `references/api-map.md` | 接口清单、请求/响应形状、加密细节、实测记录 |
| `references/tutorial.md` | 完整教程：自然语言用法 + 不装 DSH 时直接调 HTTP API（curl/Python）的写法 |
| `SKILL.md` | 本操作手册 |

> 仓库还带 `tests/`（离线测试，不联网）、`README.md` / `README.en.md`（给不装 DSH 的人看的门面）、
> `.github/workflows/ci.yml`。这些与技能运行无关，放进 `~/.dsh/skills/` 也不影响加载。
