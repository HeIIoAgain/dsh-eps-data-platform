# 用 DeepSeek-Harness 从 EPS 数据平台取数：完整教程

> 适用平台：**EPS数据平台**（`https://olap.epsnet.com.cn`，北京福卡斯特）
> 适用工具：**DeepSeek-Harness（dsh）** + 本仓库的 `eps-data-platform` 技能
> 版本：2026-11，接口与行为均来自真实账号实测

---

## 0. 这份教程能帮你做什么

- 在 dsh 里用**自然语言**让 agent 登录 EPS、找库、查指标、导数据、批量下载；
- 不用 dsh 的人，也能照着第 3 节**直接调 HTTP API**（curl / Python / 任意语言）；
- 避开平台上所有已知的坑：`5000 条上限`、`操作过于频繁`、`sheetId 每次重建`、`加密的 dataletBO`、
  `下载次数额度`、`直辖市/简称/县级市`等地市口径问题。

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 账号 | EPS 个人/机构账号，**手机号能收短信验证码**（本教程只走短信登录） |
| 网络 | 能访问 `https://olap.epsnet.com.cn`（机构 IP 授权账号也可） |
| 环境 | dsh 已安装；Python 3.10+；`pip install requests cryptography openpyxl` |
| 权限 | 账号需订阅对应数据库；地市级数据要在「省级县域 → 某省市县统计数据库」里找 |

> **登录约束**：本教程坚持“只用手机短信验证码登录”（`loginType=MOBILE`）。
> 发码接口前置了阿里云滑块验证码，**不要**尝试自动化发码/绕过滑块；验证码由用户本人在网页上点击获取。

---

## 2. 最快路径：用 dsh 技能（推荐）

### 2.1 安装技能

把技能目录放到 dsh 的技能根目录：

```bash
cp -r eps-data-platform ~/.dsh/skills/
# 目录结构：
# ~/.dsh/skills/eps-data-platform/
#   ├── SKILL.md                 # 操作手册
#   ├── scripts/eps_client.py    # 客户端（本教程第 3 节全部封装好了）
#   └── references/api-map.md    # 接口清单 + 加密细节
```

重启 dsh 会话后，技能列表里会出现 `eps-data-platform`。之后用自然语言触发即可，dsh 会按 SKILL.md
自动执行。

### 2.2 触发登录（唯一需要人工的一步）

在 dsh 里说：

> 用 eps-data-platform 技能登录 EPS，我的手机号是 138xxxxxxxx

agent 会让你去 `https://olap.epsnet.com.cn` 登录页选「手机验证码登录」、填手机号、点「获取验证码」
（有滑块就拖一下），然后把 6 位验证码发给它。agent 会执行：

```bash
python3 ~/.dsh/skills/eps-data-platform/scripts/eps_client.py login \
  --account 138xxxxxxxx --code 123456
```

成功后 `sid` 存到 `~/.eps_sid`（权限 600），后续命令自动复用。**sid 是凭证，不要外传。**

### 2.3 让 agent 取数（提示词模板）

```
用 eps-data-platform 技能：
1) 在 891 库（中国宏观经济数据库-年度（全国））取 2021-2025 年
   国内生产总值（亿元）、第一/二/三产业增加值、人均 GDP；
2) 输出一个 Excel（宽表+长表两个 sheet）和一个 CSV。
```

agent 内部会做：

```bash
CLI=~/.dsh/skills/eps-data-platform/scripts/eps_client.py
python3 $CLI tree                              # 9 个研究系列
python3 $CLI cubes --filter 宏观经济            # 找 cubeId
python3 $CLI dims --cube 891                   # 看维度布局 + sheetId
python3 $CLI dimtree --cube 891 --dim indicator --parent 0101 --depth 3  # 找指标代码
python3 $CLI query --cube 891 \
  --dims '{"time":["2024010101"],"indicator":["01010103"]}' \
  --out gdp.csv --long gdp_long.csv --xlsx gdp.xlsx
```

### 2.4 常用提示词

| 需求 | 对 dsh 说 |
|---|---|
| 看有哪些库 | “列出 EPS 的 9 个研究系列/宏观经济的子库” |
| 查指标代码 | “在 891 库里找 2024 年 GDP 的指标代码” |
| 单表取数 | “取 891 库 2024 年 GDP 和人均 GDP” |
| 批量取数 | “把 891 库 2021-2025 年所有农业相关指标导成 Excel” |
| 按地市取数 | “去 XX省市县统计数据库，取年度（市级）表的地市级农作物播种面积/产量” |
| 查下载额度 | “查一下我 EPS 账号今天还能下载几次” |

---

## 3. 不用 dsh：直接调 API

所有接口都在 `https://olap.epsnet.com.cn`，业务接口在 `/eps` 前缀，登录/用户接口在 `/user` 前缀。

### 3.1 登录（短信验证码）

```bash
curl 'https://olap.epsnet.com.cn/user/login/login?account=138xxxxxxxx&verifyCode=123456&loginType=MOBILE' \
  -H 'lang: 1'
# => {"success":true,"sid":"...","userInfo":{...}}
```

拿到 `sid` 后，所有请求带 `?sid=<sid>`（平台也认 cookie）。用 `userInfo` 验证：

```bash
curl 'https://olap.epsnet.com.cn/user/login/userInfo?sid=<sid>' -H 'lang: 1'
```

### 3.2 找库（免登录）

```bash
# 9 个研究系列
curl 'https://olap.epsnet.com.cn/eps/metaCube/listMetaCubeTree.do'

# 全部 900+ 库（一次全量返回，分页字段只是摆设）
curl 'https://olap.epsnet.com.cn/eps/metaCube/listMetaCube.do?currentPage=1'
```

关键字段：`cubeId`、`cubeNameZh/cubeFnameZh`、`folderType`、`pid`、`startDate/lastDate`。

> **`folderType` 是最容易搞错的一点**：
> `0` = 目录（如 130000 宏观经济、9 中国宏观经济数据库），`1` = 真正能查的数据表
> （如 891 年度（全国）、897 月度（全国）、900 年度（分省分行业））。
> `getDimension` / `center.do` 的 `cubeId` 必须是 **folderType=1**。

### 3.3 拿查询条件（sheetId + 维度布局）

```bash
curl 'https://olap.epsnet.com.cn/eps/getDimension.do?cubeId=891&sid=<sid>' -H 'lang: 1'
```

返回：

```json
{"success":true, "dataletBO":"<AES 密文>", "visitAuth":true, "cubeAuth":true}
```

`dataletBO` **是加密的**，解密方法见附录 B。解开后关键字段：

```json
{
  "sheetId": "68d4473c-...",          // center.do / 下载都要用；每次调用都会新建
  "freqId": 1,
  "metaLefts": ["indicator"],          // 行维度 → 对应 metaColumns
  "metaTops": ["time"],                // 列维度 → 对应 metaRows
  "fixeds": [],                        // 固定维度 → 对应 fix
  "allDimensions": {"dimensionVOList": [
     {"codeName":"indicator", "dimName":"指标",
      "objList":[{"dimCode":"01","dimName":"国民经济核算","isParent":true}]},
     {"codeName":"time", "dimName":"时间", "objList":[{"dimCode":"2024010101","dimName":"2024"}]}
  ]},
  "dimensionNameMap": {"indicator":"指标","time":"时间"}
}
```

找成员/指标子节点：

```bash
# 维度子节点（返回加密 dimensionList，同样是 AES 密文）
curl 'https://olap.epsnet.com.cn/eps/getDimensionList.do?sheetId=<sheetId>&dimType=indicator&parentCode=0101&sid=<sid>'

# 某维度全部代码（只有 code，没有名称）
curl 'https://olap.epsnet.com.cn/eps/getDimensionAll.do?sheetId=<sheetId>&dimType=indicator&sid=<sid>'

# 按关键词搜指标（返回加密 dimensionList，带 dimName）
curl 'https://olap.epsnet.com.cn/eps/searchDimension.do?cubeId=891&dimensionId=indicator&keyword=播种面积&sid=<sid>'
```

### 3.4 取数（核心接口）

```bash
curl -X POST 'https://olap.epsnet.com.cn/eps/center.do?sid=<sid>' \
  -H 'Content-Type: application/json' -H 'lang: 1' \
  -d '{
    "cubeId": 891,
    "sheetId": "<3.3 拿到的 sheetId>",
    "dims": "[{\"codeName\":\"time\",\"codes\":[\"2024010101\"]},{\"codeName\":\"indicator\",\"codes\":[\"01010103\"]}]",
    "metaColumns": "indicator",
    "metaRows": "time",
    "fix": "",
    "s1": {"dealStr": "empty"},
    "s2": {"method": "", "type": ""},
    "s3": {"index8020": "", "fontStyle8020": "", "bgColor8020": ""},
    "s4": {"orderStr": "", "index": ""},
    "s5": {"dealStr": "", "showBackColor": "", "showFontStyle": ""}
  }'
```

返回 `{"success":true,"dataletBO":{...}}`（**明文**）：

- `cellBOs`：二维数组。前 `len(metaTops)` 行是表头；之后每行前 `len(metaLefts)` 格是行标题，其余是数值。
- 单元格：`{"showValue": "...", "cellType": "VAL"|"indicator"|"APPEND", "rowSpan"/"colSpan", "obj"}`。
- `dataCount`：有值的格子数。

**取数的三条硬规则**：

1. `dims` 必须是**字符串**（JSON 再 stringify 一层），元素 `{codeName, codes:[...]}`；
2. `metaColumns` = 行维度（`metaLefts`）用 `-` 连接；`metaRows` = 列维度（`metaTops`）；`fix` = 固定维度；
   `dims` 里的每个维度必须出现在这三者之一；
3. **单次查询最多 5000 条**（账号级 `querySize`，本账号所有库都是 5000），超了返回
   `"单次查询数据量超过5000条，请重新选择"` → 必须切块。

### 3.5 导出（平台原生 Excel/CSV）

```bash
# 1) 下载前检查（不扣次数），拿 sign，同时返回额度信息
curl 'https://olap.epsnet.com.cn/eps/checkDownload1.do?sheetId=<sheetId>&sid=<sid>'
# => {"success":true,"canDownload":true,"sign":"...",
#     "downloadCount":200,"todayDownloadCount":0,"maxRows":1000000,"partSize":50000,
#     "nowDownloadSize":..., "previewRows":[...]}

# 2) 真正下载（这一步才扣次数）
curl -o data.xlsx \
  'https://olap.epsnet.com.cn/eps/download.do?sheetId=<sheetId>&sid=<sid>&sign=<sign>&dataType=2&exportType=XLSX&lang=1'
```

`exportType` 可选 `XLSX / XLS / CSV / PDF / DTA / TXT`；`dataType` 1/2/3 是表格样式。

---

## 4. 必须知道的 8 个要点（都是踩过的坑）

1. **`sheetId` 每次 `getDimension` 都会新建**：`center.do` 和下载必须用紧邻那一次的 sheetId。
   脚本里的 `query`/`download` 都是现取现用；不要跨命令复用旧 sheetId。
2. **`folderType` 0/1**：目录不能查，只有 `folderType=1` 的数据表能查。
3. **代码是长码**：`time` 的 2024 年写 `2024010101`（不是 `2024`）；`indicator` 的 GDP 写 `01010103`。
   代码必须用树里的 `dimCode`。
4. **维度节点分“数据/目录”**：`IS_VAL=1` 或 `isEnd=1` 的才有数值；`IS_VAL=0` 只是分类目录，查不出数。
   `dimtree` 命令会用 `[数据]/[目录]` 标出来。
5. **`dataletBO` 加密**：`getDimension` / `getDimensionList` / `searchDimension` 返回的 `dataletBO`、
   `dimensionList` 是 AES-128-CBC 密文，要解密（附录 B）；`center.do` 返回的 `dataletBO` 是明文。
6. **5000 条上限 → 切块**：按 `指标 × 地区 × 年份 ≤ 4500` 切，逐块 `getDimension → center.do → 下载`。
7. **频控**：连续查几次会返回 `{"errorCode":"RATE_LIMITED","message":"操作过于频繁，请稍候。"}`，
   大约要等 1 分钟。**能一次查完就不要拆多次**；必须拆时每次间隔 60s，脚本要对“频繁/稍候”做指数退避。
8. **下载额度**：每库每日 **200 次**（`downloadCount`），`checkDownload1` 不扣次数，
   `download.do` 才扣；单次下载最大 100 万行（`maxRows`），分批 5 万（`partSize`）。
   查询本身没有每日次数，只有频控。

---

## 5. 批量取数：库的层级与逐省方案

EPS 的“地市级农作物”数据藏在**省级县域**系列里，结构如下：

```
宏观经济
└── 省级县域（cubeId 190000，folderType=0）
    └── 某省市县统计数据库（如 安徽市县统计数据库，folderType=0）
        ├── 年度（市级）     ← 地市级！就是我们需要的
        ├── 年度（县级）
        ├── 年度（分行业）
        └── ...
```

其它相关系列：

| 系列 | cubeId | 说明 |
|---|---|---|
| 中国区域经济数据库-年度(分市) | 775 | 全国 426 市/区，只有农业汇总指标（总播种面积、粮食产量等） |
| 中国区域经济数据库-年度(分县) | 776 | 县级汇总 |
| 中国农林数据库-年度(分省) | 812 | 分省、**分作物**的面积/产量/单产（139 个指标） |
| 中国城市数据库 | 627 | 地市级，主要农产品产量（无分作物面积/单产） |
| 省级县域（各省市县库） | 190000 子库 | **地市级分作物面积/产量/单产在这里**（各省结构不同） |
| 市级县域（各市数据库） | 195000 子库 | 单市的分县数据 |

**逐省方案**（每个省的表名、指标代码、地市命名都不同，不能一套逻辑套全国）：

```
for 每个省:
    1) 在该省《XX市县统计数据库》的子表里选“市级表”：
       年度（市级） / 年度（分城市） / 年度（分盟市） / 年度（分市县） / 直辖市用 年度（分区县）
       —— 必须表里有 region 维度（有的“年度（全市）”表没有，不能用）
    2) 展开 region 维，筛出地级市：
       - 以《中国区域经济数据库-年度(分市)》(775) 的地市名单为权威，剔除县级市/省直管县
       - 地名要做简称/全称/民族自治州匹配（如“广州” vs “广州市”、“临夏州” vs “临夏回族自治州”）
       - 直辖市取市辖区
    3) 找作物指标：searchDimension 搜 播种面积/产量/单产/面积，再递归展开命中的父节点
       —— 相似指标、新旧口径指标全部保留，不要甄别
    4) 切块（≤4500 格/块）逐块导出 xlsx，断点续跑（记录已完成的省/块）
    5) 合并成长表：省份, 省份代码, 地市, 地市代码, 指标, 指标代码, 年份, 数值
```

已实测的特殊情况（写代码时按需处理）：

- **内蒙古**：默认会选到「年度（分城市）」（城市建设表），要强制用「年度（分盟市）」（1075）；
- **北京/重庆/天津**：市级表没有 region 维度 → 用「分区县」，区县=地级；
- **广东**：表里是简称（广州/深圳），775 是全称（广州市），要模糊匹配；
- **安徽**：要剔除潜山/无为/广德（县级市）和省直管县，只留 16 个地级市；
- **新疆**：平台表只覆盖 13 个地州（缺石河子/阿拉尔/图木舒克/五家渠/克州），按平台实际导；
- **上海/福建**：市县库的市级表本身没有农业指标（上海农业只在全市口径的「分行业」；福建农业只在
  「年度（县级）」），需要改用县级或「中国城市数据库」补充。

---

## 6. 排错表

| 现象 | 原因 / 处理 |
|---|---|
| `{"success":false,"message":"请登录后重试"}` | 没 sid 或 sid 过期 → 重新短信登录 |
| `验证码错误，请重新输入！` / `请先获取验证码！` | 码过期/没发码 → 重新点“获取验证码”拿新码 |
| `{"errorCode":"RATE_LIMITED","message":"操作过于频繁，请稍候。"}` | 频控 → 等 60s，合并查询 |
| `单次查询数据量超过5000条，请重新选择` | 一次查太多 → 按指标/年份/地区切块 |
| 查询成功但 `cellBOs` 为空 / `dataCount=0` | 用了目录节点、年份锁定、或该表没这个维度 → 换 `[数据]` 代码；先 `dims` 看布局 |
| `登录已过期，请重新登录！` / `loginStatus:"fail"` | sid 过期 → 重新登录 |
| `dataletBO` 解不出来 | 前端加密常量可能变了 → 重新扒 `index-*.js` 里的 `addceffs` 常量并更新 key/iv |
| `您的账号下载次数已达到今日上限` | 当日 200 次用完 → 次日再下；本地 CSV/Excel 导出不占下载次数 |
| `暂无数据，请调整维度或打开联动后重试` | 该选择下平台没有数据 → 换指标/年份/地区，或确认表里是否包含该地市 |
| 地区数比预期少 | 平台表覆盖范围问题（如天津表只覆盖 15 个区），按实际导，不要硬凑 |

---

## 7. 合规与数据质量

- **只用自己/自己机构有权限的账号**；不绕过登录、订阅、下载次数、验证码；
- 不做全库扫描/高频轮询/转卖数据；批量下载前先确认平台条款；
- `sid`、手机号、验证码、cookie 不要写进示例文件、日志、提交记录；
- 数值保留平台原始单位（千公顷/万吨/吨/千克每公顷…），缺失留空、不插值；
- 引用数据时保留来源：**EPS数据平台（olap.epsnet.com.cn）+ 库名 + 指标代码**。

---

## 附录 A：接口清单速查

| 用途 | 接口 |
|---|---|
| 短信验证码登录 | `GET /user/login/login?account=&verifyCode=&loginType=MOBILE` |
| 用户信息/权限 | `GET /user/login/userInfo?sid=` |
| 9 个研究系列 | `GET /eps/metaCube/listMetaCubeTree.do`（免登录） |
| 全部库列表 | `GET /eps/metaCube/listMetaCube.do?currentPage=1`（免登录） |
| 单库详情 | `GET /eps/metaCube/getMetaCube.do?cubeId=` |
| 维度布局+sheetId | `GET /eps/getDimension.do?cubeId=&sid=`（加密 dataletBO） |
| 维度子节点 | `GET /eps/getDimensionList.do?sheetId=&dimType=&parentCode=`（加密） |
| 维度全部代码 | `GET /eps/getDimensionAll.do?sheetId=&dimType=` |
| 搜指标/成员 | `GET /eps/searchDimension.do?cubeId=&dimensionId=indicator&keyword=`（加密） |
| **取数** | `POST /eps/center.do?sid=`（JSON body） |
| 下载前检查/额度 | `GET /eps/checkDownload1.do?sheetId=&sid=` |
| **下载** | `GET /eps/download.do?sheetId=&sid=&sign=&dataType=2&exportType=XLSX&lang=1` |
| 下载任务列表 | `GET /eps/v2/download/tasks?sid=` |
| Swagger | `/eps/v2/api-docs`、`/user/v2/api-docs`、`/eps/swagger-ui.html` |

## 附录 B：`dataletBO` 解密（Python）

前端 JS 里写死了两段常量，等价实现：

```python
import base64, hashlib, json
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

JS_KEY = "U2FsdGVkX1+sA1gKG00U89ovJjaeAcSP3RxXwvlGNWM7yJiE1eeGq6s2zfp9UyHs"  # KEY=IV

def _evp(pw: bytes, salt: bytes, size: int = 48) -> bytes:
    out, prev = b"", b""
    while len(out) < size:
        prev = hashlib.md5(prev + pw + salt).digest()
        out += prev
    return out[:size]

def _passphrase_decrypt(b64: str) -> bytes:
    raw = base64.b64decode(b64)
    assert raw[:8] == b"Salted__"
    salt, data = raw[8:16], raw[16:]
    key_iv = _evp(b"addceffs", salt, 48)      # CryptoJS 默认 keySize=256
    key, iv = key_iv[:32], key_iv[32:48]
    d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = d.update(data) + d.finalize()
    return pt[:-pt[-1]]

AES_KEY = AES_IV = _passphrase_decrypt(JS_KEY)[:16]   # 明文是 b"1321321561321321"

def decrypt_datalet(payload: str) -> dict:
    raw = base64.b64decode(payload)
    d = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV)).decryptor()
    pt = d.update(raw) + d.finalize()
    return json.loads(pt[:-pt[-1]].decode("utf-8"))
```

## 附录 C：`cellBOs` 解析成表

```python
def parse_table(datalet: dict):
    tops  = [x if isinstance(x, str) else x.get("codeName") for x in datalet["metaTops"]]
    lefts = [x if isinstance(x, str) else x.get("codeName") for x in datalet["metaLefts"]]
    n_top, n_left = len(tops), len(lefts)
    grid = [[(c or {}).get("showValue", "") if isinstance(c, dict) else (c or "")
             for c in row] for row in datalet["cellBOs"]]
    header = grid[:n_top]        # 表头行
    data   = grid[n_top:]        # 数据行；前 n_left 格是行标题
    return header, data
```

## 附录 D：文件与命令速查

```bash
# 技能目录（已封装全部逻辑）
~/.dsh/skills/eps-data-platform/
  ├── SKILL.md
  ├── scripts/eps_client.py
  └── references/api-map.md

# 常用命令
CLI=~/.dsh/skills/eps-data-platform/scripts/eps_client.py
python3 $CLI login --account <手机号> [--code <6位码>]
python3 $CLI whoami
python3 $CLI tree
python3 $CLI cubes --filter 宏观经济
python3 $CLI dims --cube 891 [--deep] [--out dims_891.json]
python3 $CLI dimtree --cube 891 --dim indicator --parent 0101 --depth 3
python3 $CLI query --cube 891 --dims '<json>' --out a.csv --long a_long.csv --xlsx a.xlsx
python3 $CLI download --cube 891 --dims '<json>' --out a.xlsx --export-type XLSX
python3 $CLI quota --cube 891        # 查每日下载次数/已用/单次限制
```

> 提示：`query` 是“查询后本地生成 CSV/Excel”，不消耗平台下载次数；`download` 才是走平台导出，
> 会扣每日 200 次的额度。
