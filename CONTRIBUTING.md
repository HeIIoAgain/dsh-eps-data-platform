# 贡献指南

感谢你愿意改进 `dsh-eps-data-platform`。这个仓库的主体是一个 DSH 技能
（`SKILL.md` + `references/`）和一个纯 Python 命令行客户端（`scripts/eps_client.py`）。

## 环境准备

```bash
git clone https://github.com/HeIIoAgain/dsh-eps-data-platform.git
cd dsh-eps-data-platform
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## 提交前必跑

```bash
python -m ruff check .           # 代码风格
python -m pytest -q              # 离线测试，不需要 EPS 账号
```

两个命令都必须通过，CI 跑的是同一套（Python 3.10 / 3.11 / 3.12）。

## 测试原则

- **`tests/` 里的测试不联网、不需要账号。** CI 没有 EPS 凭据，也不该有。
- 涉及真实接口的改动（新端点、参数变化、加密常量变更），在 PR 描述里贴上
  **脱敏后的**请求与响应片段（去掉 `sid`、手机号、`sheetId`、机构名）。
- 导出格式（CSV/Excel）是契约：改动会破坏下游脚本，请同时更新
  `references/api-map.md` 与 `CHANGELOG.md`。

## 千万不要提交

- `~/.eps_sid`、任何 `sid`、手机号、短信验证码、cookie、抓包原文；
- 导出的数据文件（`*.csv` / `*.xlsx`，已被 `.gitignore` 忽略）。

仓库里 `tests/test_repo_hygiene.py` 会扫描疑似凭据，命中即 CI 失败。

## 提交信息

采用 [Conventional Commits](https://www.conventionalcommits.org/zh-hans/)：

```
feat: 支持分省库的 region 维度
fix: dimtree 在 isParent 为字符串时不再下钻
docs: 补下载配额的实测字段
```

- 一个提交做一件事；正文写「为什么」，不要重复 diff。
- 用户可见的行为变化记入 `CHANGELOG.md` 的 `### Added / ### Changed / ### Fixed`。

## Issue / PR

- Bug 请用 Bug report 模板，附最小复现命令与脱敏输出。
- 新功能请先开 Issue 说明使用场景，避免大改后被拒。
- PR 请保持小而聚焦；CI 绿了再请求 review。
