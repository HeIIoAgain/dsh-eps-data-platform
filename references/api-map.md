# EPS 数据平台接口地图（olap.epsnet.com.cn）

做这个技能时（2026-11-16）在真实账号上验证过的接口与形状。平台改版后若报错，
先拉 Swagger 对参数：`https://olap.epsnet.com.cn/eps/v2/api-docs`、
`https://olap.epsnet.com.cn/user/v2/api-docs`、UI 在 `/eps/swagger-ui.html`。

## 1. 服务前缀

前端为 Vite SPA（`/assets/index-*.js`），后端 Java 微服务，网关前缀：

| 前缀 | 作用 | Swagger |
|---|---|---|
| `/eps` | OLAP 取数、维度、下载、元数据库 | `/eps/v2/api-docs`（1.6MB，1000+ 路径） |
| `/user` | 登录、用户信息、验证码、订单 | `/user/v2/api-docs` |
| `/es` | 检索（需登录） | 401 |
| `/cms` | 帮助中心 | — |
| `/ruoyi` | 用户中心后台 | — |

所有业务接口的身份凭证是 **`sid`**：作为 query 参数传（`?sid=xxx`），平台也种 cookie；
前端存在 `localStorage.sid`。

## 2. 登录（只允许短信验证码这一种）

```bash
# 登录（网页"手机验证码登录"调的就是它）
GET /user/login/login?account=<手机号>&verifyCode=<6位码>&loginType=MOBILE
# => {"success":true,"sid":"...","userInfo":{...}}
```

- 发码链路（**不在脚本里使用**）：`GET /user/verify/getSign?account=` +
  `GET /user/verify/sendCode?account=&sign=`，前置阿里云滑块验证码
  （页面 `window.AliyunCaptchaConfig = {region:"cn", prefix:"1jkcuw", sceneId:"11hz7xhj"}`，
  请求头 `captchaVerifyParam` / `encryptKey`）。验证码必须由用户在网页上手动获取。
- 已验证返回：未发码 → `请先获取验证码！`；码错 → `验证码错误，请重新输入！`；
  未登录带 sid 请求 → `请登录后重试`；sid 失效 → `登录已过期，请重新登录！` /
  `loginStatus:"fail"`。
- `GET /user/login/userInfo?sid=` 返回 `userInfo`（`userId/realname/groupName/endDate/
  phone/email/metaCubeList/roleList/...`），可用来确认账号与订阅。
- 其它登录方式（`PWD / GROUP_PWD / IP / CARSI / WECHAT`）接口存在，但本技能的约定是
  **只用短信验证码**，不要尝试。

## 3. 元数据（免登录）

```bash
GET /eps/metaCube/listMetaCubeTree.do                 # 9 个研究系列
GET /eps/metaCube/listMetaCube.do?currentPage=1       # 全部 900+ 库（一次全返回）
GET /eps/metaCube/getMetaCube.do?cubeId=              # 单库详情（该接口对部分 id 会返回“获取失败”）
```

库字段：`cubeId / cubeNameZh / cubeFnameZh / descZh / pid / folderType / startDate /
lastDate`。`folderType`：`0` 目录、`1` 数据表。已知：`130000` 宏观经济（目录）→ `9`
中国宏观经济数据库（目录）→ `891` 年度（全国）、`897` 月度（全国）、`900` 年度（分省分行业）
等数据表；`120000` 上市公司（目录）→ `765` 中国上市公司综合数据库 → `766/767...`。

## 4. 维度

```bash
# 布局 + sheetId（返回加密 dataletBO）
GET /eps/getDimension.do?cubeId=<folderType=1>&sid=<sid>       # header: lang: 1
#   => {"success":true,"dataletBO":"<密文>","visitAuth":true,"cubeAuth":true}

# 成员子节点（返回加密 dimensionList）
GET /eps/getDimensionList.do?sheetId=&dimType=<codeName>&parentCode=<dimCode>&sid=
# 某维度全部代码
GET /eps/getDimensionAll.do?sheetId=&dimType=&sid=
# 按关键词搜维度成员（返回加密 dimensionList）
GET /eps/searchDimension.do?cubeId=&keyword=&sid=
# 已选代码的父级树
POST /eps/getDimensionParent.do?sid=  body: {"cubeId":..,"dimensionId":..,"dimCodes":"..."}
```

`getDimension.do` 解密后（`dataletBO`）：

```json
{
  "sheetId": "68d4473c-...",           // center.do / 下载用，每次调用都会新建
  "freqId": 1,
  "metaLefts": ["indicator"],           // 行维度（→ metaColumns）
  "metaTops": ["time"],                 // 列维度（→ metaRows）
  "fixeds": [],                         // 固定维度（→ fix）
  "allDimensions": {"dimensionVOList": [
      {"dimensionId":"indicator", "codeName":"indicator", "dimensionName":null,
       "objList":[{"dimCode":"01","dimName":"国民经济核算","parentId":"-1",
                   "isParent":true,"isEnd":0,"chkDisabled":false}, ...]}
  ]},
  "dimensionNameMap": {"indicator":"指标","time":"时间"}
}
```

成员字段：`dimCode / dimName / parentId / isParent / isEnd / IS_VAL / IS_END /
chkDisabled / dimFName / dimComment / ORD`。

- `IS_VAL=1` 或 `isEnd=1` → 有数值，可放进查询（脚本标 `[数据]`）。
- `IS_VAL=0` 且 `isParent=true` → 纯分类目录，查不出数（标 `[目录]`）。
- 注意：`isParent=true` 的节点也可能 `IS_VAL=1`（例如 `01010103` 国内生产总值（亿元）
  自身有值，下面还挂三次产业），所以"叶子才可查"是错的，按 `IS_VAL/isEnd` 判断。

代码实例（`891` 年度全国）：

| 维度 | 代码示例 |
|---|---|
| time | `2025010101`=2025、`2024010101`=2024、…（年度）；月度类似全码 |
| indicator | `01` 国民经济核算（目录）、`0101` 国内生产总值（目录）、`01010103` 国内生产总值（亿元）、`01010101` 国民总收入（亿元）、`01010101a` 人均国民总收入（元）、`0101010301` 第一产业增加值（亿元）… |

## 5. 取数

```bash
POST /eps/center.do?sid=<sid>    Content-Type: application/json, header lang: 1
```

```json
{
  "cubeId": 891,
  "sheetId": "<getDimension 返回的>",
  "dims": "[{\"codeName\":\"time\",\"codes\":[\"2024010101\"]},{\"codeName\":\"indicator\",\"codes\":[\"01010103\"]}]",
  "metaColumns": "indicator",
  "metaRows": "time",
  "fix": "",
  "s1": {"dealStr": "empty"},
  "s2": {"method": "", "type": ""},
  "s3": {"index8020": "", "fontStyle8020": "", "bgColor8020": ""},
  "s4": {"orderStr": "", "index": ""},
  "s5": {"dealStr": "", "showBackColor": "", "showFontStyle": ""}
}
```

- `dims` 必须是**字符串**；`metaColumns`/`metaRows`/`fix` 用 `-` 连接维度 codeName。
- 返回 `{"success":true,"dataletBO":{...}}`，**明文**：

```json
{"cellBOs": [[...], ...], "metaTops": ["time"], "metaLefts": ["indicator"],
 "dataCount": 65, "sheetId": "...", "dimensionNameMap": {...}, "selectDimensions": {...}}
```

`cellBOs` 布局：前 `len(metaTops)` 行是表头（含 `rowSpan/colSpan` 合并），之后每行前
`len(metaLefts)` 格是行标题，其余是数值列。单元格：`{"showValue": ..., "cellType":
"VAL"|"indicator"|"APPEND", "obj": ...}`，数值在 `showValue`。

- 频控：连续查询会返回
  `{"success":false,"errorCode":"RATE_LIMITED","message":"操作过于频繁，请稍候。"}`，
  约 1 分钟恢复。建议合并成一次查询（多指标 × 多年份），拆多次时 sleep 60s。
- 前端限制：单次约 5000 格（更高权限账号更多）。

## 6. 下载（消耗下载次数）

```bash
# 校验 + 拿 sign（只检查，不扣次数；需要先有一次成功的 center.do）
GET /eps/checkDownload1.do?sheetId=<sheetId>&sid=<sid>
# response 关键字段：
#   downloadCount        每日下载次数上限（本账号 200）
#   todayDownloadCount   今日已用（当前 0）
#   maxRows=1000000      单次下载最大行数
#   partSize=50000       分批大小
#   overLimit=false      是否超限
#   canDownload=true     是否可下载
#   nowDownloadSize      本次数据行数
#   previewRows          预览数据
#   noData / message     无数据时会 success:false + "暂无数据，请调整维度或打开联动后重试"

# 旧版/其它：
GET /eps/checkDownload.do?sheetId=&sid=      # {downloadSize, maxDownloadSize, canDownload, sign}
GET /eps/getAllDownloadCount                  # {count: 1603423587} 平台全站累计，不是个人配额
GET /eps/checkDownloadAuth.do?sheetId=&sid=   # 权限检查（含试用数据时会拒绝下载）

# 下载（GET，浏览器里就是直接跳这个地址）
GET /eps/download.do?sheetId=&sid=&sign=&dataType=&exportType=&lang=1
# exportType: XLSX / XLS / CSV / PDF / DTA / TXT；dataType: 1/2/3（样式）
```

另有 `/eps/downloadData.do?sheetId=&exportType=&dataType=&showVal=&sid=`、
下载任务接口 `/eps/v2/download/tasks`、`/eps/v2/download/tasks/file`。

## 7. 加密细节（`dataletBO` / `dimensionList` 等）

前端 `index-*.js` 中：

```js
class Ke {
  KEY = "U2FsdGVkX1+sA1gKG00U89ovJjaeAcSP3RxXwvlGNWM7yJiE1eeGq6s2zfp9UyHs";
  IV  = KEY;
  decrypt(e) {
    const key = CryptoJS.enc.Utf8.parse(this.tripleAesDecrypt(this.KEY));
    const iv  = CryptoJS.enc.Utf8.parse(this.tripleAesDecrypt(this.IV));
    return CryptoJS.AES.decrypt(e, key, {iv, mode: CBC, padding: Pkcs7}).toString(Utf8);
  }
  tripleAesDecrypt(e) { return CryptoJS.AES.decrypt(e, "addceffs").toString(Utf8); }
}
```

等价 Python（已实现在 `scripts/eps_client.py`）：

1. CryptoJS passphrase 模式解密 `KEY`：base64 → `Salted__`+8B salt+ct →
   `EVP_BytesToKey(MD5, passphrase="addceffs", salt, 48)` → key=前 32B、iv=后 16B →
   AES-256-CBC 解密 → 明文 `"1321321561321321"`。
2. 用它作 key 和 iv（UTF-8，各 16 字节）做 **AES-128-CBC/PKCS7** 解密 `dataletBO`。

`center.do` 返回的 `dataletBO` 是明文，不需要解密（前端也没有解）。

## 8. 其它相关接口（备用）

| 用途 | 接口 |
|---|---|
| 时间序列/报告 | `GET /eps/getAllReportByCubeId.do?cubeId=`、`POST /eps/v2/report/*` |
| 我的收藏 | `GET /eps/collection/getAll`、`/eps/v2/collection/*` |
| 云分析 | `/eps/getReportForm.do`、`/eps/center.do`、`/eps/v2/center.do` |
| 检索 | `POST /es/search/match`（需登录，参数未知） |
| 登录态 | `GET /user/login/userInfo?sid=`、`GET /user/login/logout` |

## 9. 实测记录（2026-11-16）

```
GET  /eps/metaCube/listMetaCubeTree.do                 -> 200, 9 个系列
GET  /eps/metaCube/listMetaCube.do?currentPage=1       -> 200, 937 个库（folderType 0/1）
GET  /eps/getDimension.do?cubeId=891                   -> dataletBO 解密成功
       sheetId=..., metaLefts=[indicator], metaTops=[time]
GET  /eps/getDimensionList.do?...parentCode=0101       -> 加密 dimensionList 解密成功
POST /eps/center.do  time=[2024010101,2023010101,2022010101]
       indicator=[01010103,01010101]                    -> 成功，见下表
```

| 指标 | 2024 | 2023 | 2022 |
|---|---|---|---|
| 国内生产总值（亿元） | 1348066.186 | 1294271.744 | 1234029.355 |
| 国民总收入（亿元） | 1340429.031 | 1284773.909 | 1223706.809 |

配额实测：`checkDownload1.do` -> `downloadCount=200`、`todayDownloadCount=0`、`maxRows=1000000`、
`partSize=50000`；`userInfo.metaCubeList[].querySize` 多为 5000（30 个库 50000、9 个库 10000）。
未测：`download.do`（避免消耗账号下载次数）；`/es` 检索接口。
