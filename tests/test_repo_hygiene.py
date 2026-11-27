"""Guards the repo's own promises: the skill manifest and the docs stay honest.

A skill repo is only useful if SKILL.md is found and every file it points at
actually ships. These checks turn "README says X" into something CI verifies.
"""

from __future__ import annotations

import re
from pathlib import Path

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "SKILL.md"
REPO = "https://github.com/HeIIoAgain/dsh-eps-data-platform"


def _frontmatter() -> dict[str, str]:
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with a YAML frontmatter block"
    block = text.split("---\n", 2)[1]
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_skill_frontmatter_has_required_fields():
    fm = _frontmatter()
    assert fm["name"] == "eps-data-platform"
    assert fm["description"].startswith("Use when")
    assert len(fm["description"]) > 80
    assert fm["whenToUse"]


def test_every_file_mentioned_in_skill_md_exists():
    text = SKILL.read_text(encoding="utf-8")
    for rel in ("scripts/eps_client.py", "references/api-map.md", "references/tutorial.md"):
        assert rel in text, f"SKILL.md no longer mentions {rel}"
        assert (ROOT / rel).is_file(), f"SKILL.md points at missing file: {rel}"


def test_package_metadata_matches_repo_name():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    assert project["name"] == "eps-data-platform"
    assert project["urls"]["Repository"] == REPO
    assert "eps_client:main" == project["scripts"]["eps-client"]
    # 版本与 CHANGELOG 顶层标题一致，避免发版时忘记改一处
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{project['version']}]" in changelog


def test_readme_has_no_placeholders():
    for name in ("README.md", "README.en.md"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for bad in ("OWNER", "<your-name>", "YOURNAME", "example.com/heiioagain"):
            assert bad not in text, f"{name} still contains placeholder {bad!r}"
        assert REPO in text, f"{name} must link to the canonical repo URL"


def test_readme_badges_point_at_this_repo():
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for url in re.findall(r"!\[[^\]]*\]\(([^)]*)\)", text):
        assert ("HeIIoAgain/dsh-eps-data-platform" in url
                or url.startswith("https://img.shields.io/")), f"badge points elsewhere: {url}"


def test_readme_discloses_api_dependency_in_first_two_lines():
    """第一屏就要说清楚：这是调 EPS 数据平台 Web API 的工具，不是网页抓取。"""
    for name in ("README.md", "README.en.md"):
        head = "\n".join((ROOT / name).read_text(encoding="utf-8").splitlines()[:2])
        assert "EPS" in head, f"{name} 开头两行没提 EPS"
        assert "API" in head, f"{name} 开头两行没说明是调 API"
        assert "olap.epsnet.com.cn" in head, f"{name} 开头两行没给出 API 域名"


def test_required_root_files_exist():
    for name in (
        "README.md",
        "README.en.md",
        "LICENSE",
        "CHANGELOG.md",
        "CONTRIBUTING.md",
        "SECURITY.md",
        ".gitignore",
        ".editorconfig",
        ".github/workflows/ci.yml",
        ".github/dependabot.yml",
    ):
        assert (ROOT / name).is_file(), f"missing required file: {name}"


def test_gitignore_covers_credentials_and_outputs():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.csv", "*.xlsx", ".eps_sid", ".env"):
        assert pattern in ignored, f".gitignore should cover {pattern}"


def test_repository_contains_no_credentials():
    """sid / 手机号 / token 不该出现在任何进仓库的文件里。"""
    phone = re.compile(r"(?<![\w.])1[3-9]\d{9}(?![\w])")
    token = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")
    sid_json = re.compile(r"['\"]sid['\"]\s*:\s*['\"][A-Za-z0-9-]{16,}['\"]")
    # 文档里的示例号码是刻意保留的占位符，不是真号
    placeholders = {"13800000000"}
    for path in ROOT.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix in {".pyc"}:
            continue
        if path == Path(__file__).resolve():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        numbers = {n for n in phone.findall(text)} - placeholders
        assert not numbers, f"possible phone number in {path.relative_to(ROOT)}: {numbers}"
        assert not token.search(text), f"possible token in {path.relative_to(ROOT)}"
        assert not sid_json.search(text), f"possible sid in {path.relative_to(ROOT)}"
