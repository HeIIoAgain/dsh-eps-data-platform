"""Offline tests: everything here runs without an EPS account or network access.

The network-dependent behaviour (login, center.do, download) is out of scope for
CI on purpose — it needs a real account, a real SMS code, and it consumes the
account's daily download quota.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import eps_client as ec  # noqa: E402


# --------------------------------------------------------------------------
# 前端加密常量
# --------------------------------------------------------------------------
def test_passphrase_decrypts_to_frontend_aes_key():
    """The hard-coded JS blob must derive to the documented 16-byte key."""
    assert ec._cryptojs_passphrase_decrypt(ec._JS_KEY_B64) == b"1321321561321321"


def test_aes_key_and_iv_are_16_bytes():
    assert len(ec.AES_KEY) == 16
    assert len(ec.AES_IV) == 16
    assert ec.AES_KEY == ec.AES_IV


def test_decrypt_datalet_bo_passes_through_plain_objects():
    """center.do returns plaintext; decrypt_dataletBO must not touch it."""
    payload = {"cellBOs": [[{"showValue": "1"}]]}
    assert ec.decrypt_dataletBO(payload) is payload
    assert ec.decrypt_dataletBO([1, 2, 3]) == [1, 2, 3]


# --------------------------------------------------------------------------
# dataletBO -> table
# --------------------------------------------------------------------------
def _sample_bo() -> dict:
    # 1 列表头（metaTops=["indicator"]），2 行数据，2 个行维度（time）
    return {
        "metaTops": ["indicator"],
        "metaLefts": ["time"],
        "cellBOs": [
            [{"showValue": ""}, {"showValue": "GDP(亿元)"}],
            [{"showValue": "2023年"}, {"showValue": "1260582.1"}],
            [{"showValue": "2024年"}, {"showValue": "1349084.0"}],
        ],
        "dataCount": 2,
        "sheetId": "sheet-123",
        "dimensionNameMap": {"time": "时间", "indicator": "指标"},
    }


def test_parse_table_splits_header_and_data():
    table = ec.parse_table(_sample_bo())
    assert table["metaTops"] == ["indicator"]
    assert table["metaLefts"] == ["time"]
    assert len(table["header"]) == 1
    assert table["data"] == [["2023年", "1260582.1"], ["2024年", "1349084.0"]]
    assert table["width"] == 2
    assert table["n_left"] == 1
    assert table["dataCount"] == 2


def test_parse_table_pads_ragged_rows():
    bo = {
        "metaTops": ["indicator"],
        "metaLefts": ["time"],
        "cellBOs": [[{"showValue": "a"}, {"showValue": "b"}], [{"showValue": "2024年"}]],
    }
    table = ec.parse_table(bo)
    assert table["data"] == [["2024年", ""]]
    assert table["width"] == 2


def test_parse_table_accepts_dict_dimensions():
    bo = {
        "metaTops": [{"codeName": "indicator"}],
        "metaLefts": [{"name": "time"}],
        "cellBOs": [[{"showValue": "h"}], [{"showValue": "2024"}, {"showValue": "1"}]],
    }
    table = ec.parse_table(bo)
    assert table["metaTops"] == ["indicator"]
    assert table["metaLefts"] == ["time"]


def test_cell_and_dim_code_helpers():
    assert ec._cell({"showValue": "x"}) == "x"
    assert ec._cell({"showValue": None}) == ""
    assert ec._cell(None) == ""
    assert ec._dim_code({"codeName": "time"}) == "time"
    assert ec._dim_code("indicator") == "indicator"


# --------------------------------------------------------------------------
# 导出
# --------------------------------------------------------------------------
def test_write_grid_csv_keeps_layout(tmp_path: Path):
    out = tmp_path / "wide.csv"
    ec.write_grid_csv(out, ec.parse_table(_sample_bo()))
    text = out.read_text(encoding="utf-8-sig")
    rows = list(csv.reader(text.splitlines()))
    assert rows[0] == ["", "GDP(亿元)"]
    assert rows[1] == ["2023年", "1260582.1"]


def test_write_long_csv_is_tidy(tmp_path: Path):
    out = tmp_path / "long.csv"
    ec.write_long_csv(out, ec.parse_table(_sample_bo()))
    rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines()))
    assert rows[0] == ["时间", "column", "value"]
    assert rows[1] == ["2023年", "GDP(亿元)", "1260582.1"]
    assert len(rows) == 3


def test_write_xlsx_creates_two_sheets_with_numbers(tmp_path: Path):
    openpyxl = pytest.importorskip("openpyxl")
    out = tmp_path / "data.xlsx"
    ec.write_xlsx(out, ec.parse_table(_sample_bo()))
    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["宽表", "长表"]
    ws = wb["宽表"]
    assert ws.cell(row=2, column=2).value == pytest.approx(1260582.1)
    assert ws.cell(row=3, column=1).value == "2024年"


# --------------------------------------------------------------------------
# CLI 契约
# --------------------------------------------------------------------------
def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as exc:
        ec.main(["--help"])
    assert exc.value.code == 0
    assert "eps_client.py" in capsys.readouterr().out


def test_cli_requires_subcommand():
    with pytest.raises(SystemExit) as exc:
        ec.main([])
    assert exc.value.code == 2


@pytest.mark.parametrize("cmd", ["login", "whoami", "tree", "cubes", "dims",
                                 "quota", "dimtree", "query", "download"])
def test_cli_documents_every_subcommand(cmd, capsys):
    with pytest.raises(SystemExit):
        ec.main([cmd, "--help"])
    assert cmd in capsys.readouterr().out


def test_sid_roundtrip(tmp_path: Path, monkeypatch):
    sid_file = tmp_path / "sid.json"
    monkeypatch.setattr(ec, "DEFAULT_SID_FILE", sid_file)
    monkeypatch.delenv("EPS_SID", raising=False)
    ec.save_sid("abc123")
    assert sid_file.exists()
    assert "abc123" in sid_file.read_text(encoding="utf-8")

    class Args:
        sid = None

    assert ec.get_sid(Args()) == "abc123"
