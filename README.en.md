# dsh-eps-data-platform

A [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) skill **and** command-line
client for pulling data out of the [EPS 数据平台](https://olap.epsnet.com.cn) (China macro,
industry, regional and listed-company statistics): it turns the web UI's
"log in → pick a cube → find the indicator → tick years → export" click-path into one repeatable
command.

[![CI](https://github.com/HeIIoAgain/dsh-eps-data-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/HeIIoAgain/dsh-eps-data-platform/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
[![DSH Skill](https://img.shields.io/badge/deepseek--harness-skill-8b5cf6.svg)](https://github.com/deepseek-ai/deepseek-harness)

English | [简体中文](README.md)

---

## What problem it solves

You want one table — "GDP by province, 2000–2024". The web UI gives you a hierarchy of click boxes:
pick a cube, hunt for a leaf node among hundreds of indicators, tick the years, choose a layout,
export a pre-formatted spreadsheet. Next month, do it all again by hand.

This skill encodes that path so an agent can repeat it on request ("pull provincial GDP for
2015–2024 into Excel"), and the bundled CLI gives everyone else the same data as a clean CSV or
Excel file that pandas / Stata can read directly.

**Boundaries** (platform rules, not laziness):

- **SMS-code login only.** The code must be requested by *you* in the browser — the send-code
  endpoint sits behind an Alibaba slider captcha, which this project neither automates nor bypasses.
- **Only cubes your account subscribes to.** Others return "no permission"; there is no back door.
- **Rate limits.** Repeated queries return "操作过于频繁，请稍候。" — wait ~60 s. A single query is
  capped at roughly 5,000 cells, so wide pulls must be split, sparingly.
- **Download quota.** ~200 native downloads/day per account, and only `download` (the platform's own
  export) consumes it — `query` writes CSV/Excel locally and costs nothing.

## Features

- **Single-file implementation** — `scripts/eps_client.py`, no EPS SDK, only `requests` + `cryptography`
- **Decrypts the frontend payload** — replicates the CryptoJS/AES derivation behind `dataletBO`, so
  the dimension tree and member codes are readable
- **Finds the long codes for you** — `dims` / `dimtree` expand the indicator tree and label nodes
  `[数据]` (queryable) vs `[目录]` (category only, returns nothing)
- **Exports you can compute on** — wide CSV (`utf-8-sig`, opens cleanly in Excel), tidy long CSV,
  and a two-sheet Excel workbook with real numeric cells
- **Quota visibility** — `quota` runs one minimal query first, and does **not** consume downloads
- **Rate-limit backoff** — exponential retry on `RATE_LIMITED`, 0.8 s default spacing
- **Credentials stay local** — `sid` lives in `~/.eps_sid` (mode 600); never in the repo, logs, or chat

## Install

### Option 1 — as a DSH skill (recommended)

`SKILL.md` sits at the repo root, so cloning into the skills directory is all it takes:

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

> The skills root defaults to `~/.dsh/skills` (override with `$DSH_HOME`). Restart DSH or open a new
> session and `eps-data-platform` appears in the skill list.

### Option 2 — CLI only (no DSH)

```bash
pip install "git+https://github.com/HeIIoAgain/dsh-eps-data-platform.git"
eps-client --help
```

That installs the `eps-client` command; running `python scripts/eps_client.py ...` works too.
`--xlsx` output needs `openpyxl` (`pip install "eps-data-platform[excel]"`); CSV works without it.

## Usage

Four steps: log in once → find a cube → find indicator codes → query.

### 1) Log in (the only manual step)

Open <https://olap.epsnet.com.cn>, choose "手机验证码登录", enter your phone number, click
"获取验证码" (drag the slider if asked), then hand the 6-digit code to the CLI:

```bash
eps-client login --account 13800000000 --code 123456
```

The `sid` is written to `~/.eps_sid` (mode 600) and reused automatically. **Treat it as a session
credential — never share it.**

### 2) Find a cube (no login needed)

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

Only `folderType=1` nodes are queryable tables; `891` is the common "annual, national" cube.

### 3) Find indicator codes

```bash
eps-client dims --cube 891                       # layout + top-level members per dimension
eps-client dimtree --cube 891 --dim indicator --parent 0101 --depth 3
```

```
  01010103  国内生产总值(亿元)                      [数据]
  01010104  ...
```

Codes are **long codes**: 2024 is `2024010101`, GDP is `01010103`. Use the `dimCode` exactly as
printed — do not guess from "2024" / "GDP".

### 4) Query

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

Wide CSV (same shape as the web table; **illustrative**, values come from the platform):

```csv
,国内生产总值(亿元)
2024年,<value>
2023年,<value>
```

Tidy long CSV (one observation per row):

```csv
时间,column,value
2024年,国内生产总值(亿元),<value>
2023年,国内生产总值(亿元),<value>
```

One query can carry many indicators × many years — **if it fits, query once**; splitting costs a
60 s wait per rate-limit window.

### As a DSH skill

> Use the eps-data-platform skill to log in to EPS; my phone number is 138xxxxxxxx

> Pull national GDP and GDP per capita for 2015–2024 and export Excel

The agent follows `SKILL.md`: resolves codes via `dims` / `dimtree`, builds the `dims` JSON, exports,
and handles errors through the built-in troubleshooting table (re-login, wait 60 s, switch to
`[数据]` codes).

### Quota (costs nothing)

```bash
eps-client quota --cube 891
```

### Native download (consumes quota)

```bash
eps-client download --cube 891 \
  --dims '{"time":["2024010101"],"indicator":["01010103"]}' \
  --out gdp.xlsx --export-type XLSX
```

Use it only when you need the platform's own multi-sheet layout, PDF, or Stata export. **It debits
your daily download quota** — don't run it unless asked.

## Configuration / exit codes / environment

| Item | Default | Meaning |
|---|---|---|
| `~/.eps_sid` | — | Session file written by `login` (mode 600); delete it to log out |
| `EPS_SID` | empty | Supply a `sid` via environment; takes precedence over the file |
| `EPS_SID_FILE` | `~/.eps_sid` | Custom session-file path |
| `--sid` | empty | Per-command `sid` |
| `--timeout` | `600` | Per-request timeout (seconds); raise it for big downloads |
| `--debug` | off | Print every request |
| `--lang` | `1` | `1` Chinese / `2` English |

| Exit code | Meaning |
|---|---|
| `0` | Success |
| `2` | API error: not logged in / expired `sid` / no permission / rate limited / no data. Also usage errors |
| `3` | Network error (unreachable, timeout, proxy) |

Proxies follow standard `requests` behaviour (`HTTPS_PROXY` / `NO_PROXY`).

## Troubleshooting

| Symptom | Fix |
|---|---|
| `请登录后重试` / `登录已过期` | `sid` expired → run `login` again |
| `操作过于频繁，请稍候。` | Rate limited → wait 60 s and merge queries |
| Empty result / `暂无数据` | You used a `[目录]` node, or the cube lacks that dimension → pick a `[数据]` code |
| `验证码错误` / `请先获取验证码` | Code expired (a few minutes) → request a new one |
| `您的账号下载次数已达到今日上限` | Daily `download` quota spent → retry tomorrow; `query` CSV costs nothing |
| Decryption failure | Frontend constant may have changed → see `references/api-map.md` |

More detail: [`references/api-map.md`](references/api-map.md) (endpoints, encryption, measured
results) and [`references/tutorial.md`](references/tutorial.md) (full tutorial, incl. plain HTTP usage).

## Platform support

| OS | Status |
|---|---|
| Windows 10/11 | ✅ |
| macOS | ✅ |
| Linux | ✅ |

Python 3.10 / 3.11 / 3.12 (all three run in CI). Pure HTTP client — no browser required.

## Repository layout

```text
dsh-eps-data-platform/
├── SKILL.md                  # DSH skill: workflow, troubleshooting table, compliance rules
├── scripts/eps_client.py     # implementation: login / catalog / dims / query / export / backoff
├── references/
│   ├── api-map.md            # endpoints, request/response shapes, encryption details
│   └── tutorial.md           # full tutorial (incl. plain HTTP usage)
├── tests/                    # offline tests (no network, no account)
├── pyproject.toml
└── .github/workflows/ci.yml
```

## Compliance & disclaimer

- Use it only with an account **you or your institution are entitled to**;
- Do not bypass login, subscriptions, download quotas, or captchas;
- Do not use it for full-catalog crawling, high-frequency polling, or reselling data;
- Cite the source: **EPS 数据平台 + cube name + indicator code**; values as returned by the platform;
- Unofficial client. Not affiliated with 北京福卡斯特 / EPS; API changes may break it.

## License

[MIT](LICENSE) © 2026 HeIIoAgain
