#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EPS 数据平台 (https://olap.epsnet.com.cn) 非官方接口客户端。

用途：在你本人（或你所在机构）拥有合法访问权限的账号下，把网页上
"选好维度 -> 查询 -> 下载" 这套操作改成脚本调用。

不要用它做越权访问、批量爬取或绕过平台的下载次数限制。

依赖：requests, cryptography   (pip install requests cryptography)

快速开始
--------
    # 1) 短信验证码登录：--account 手机号，然后输入手机收到的 6 位验证码
    #    （验证码在网页/手机短信里拿；脚本只调 loginType=MOBILE 的登录接口）
    python3 eps_client.py login --account 13800000000

    # 2) 看有哪些库
    python3 eps_client.py tree
    python3 eps_client.py cubes --filter 宏观经济

    # 3) 看某个库的维度/维度成员代码（需要登录；cubeId 要是 folderType=1 的数据表，
    #    例如 891=中国宏观经济数据库-年度（全国），目录 id 不行）
    python3 eps_client.py dims --cube 891

    # 4) 用选好的代码取数 -> CSV
    python3 eps_client.py query --cube 891 \
        --dims '{"time":["2024","2023"],"indicator":["A0101"]}' \
        --out gdp.csv

    # 5) 直接下载平台生成的 Excel（会消耗账号的下载次数）
    python3 eps_client.py download --cube 891 \
        --dims '{"time":["2024"],"indicator":["A0101"]}' \
        --out data.xlsx

实现说明（都是从前端 JS 里读出来的，不是猜的）
--------------------------------------------
* 站点是 Vite SPA，接口分四个 Java 服务，网关前缀：
    /eps  -> OLAP/取数/下载       (Swagger: /eps/v2/api-docs)
    /user -> 用户中心/登录        (Swagger: /user/v2/api-docs)
    /es   -> 检索   /cms -> 帮助   /ruoyi -> 用户中心后台
* 登录：GET /user/login/login?account=<手机号>&verifyCode=<验证码>&loginType=MOBILE
      返回 {"success":true,"sid":"...","userInfo":{...}}
      之后所有请求把 sid 作为查询参数（同时平台也用 cookie）。
* 取数三步：
    1. GET  /eps/getDimension.do?cubeId=...&sid=...
       返回 dataletBO 是 **密文**，前端用写死的 AES 解；本文文件里已复刻：
       key = iv = b"1321321561321321"（AES-128-CBC / PKCS7 / base64）
       解密后得到 sheetId、metaLefts(行维度)、metaTops(列维度)、fixeds(固定维度)、
       allDimensions.dimensionVOList(维度及成员树)、dimensionNameMap。
    2. POST /eps/center.do?sid=...   JSON body:
       {cubeId, sheetId, dims:"[{codeName,codes:[]}]", metaColumns, metaRows, fix,
        s1..s5}                                                （s1..s5 是默认样式参数）
       返回的 dataletBO.cellBOs 是明文二维数组：前 metaTops.length 行是表头，
       每行前 metaLefts.length 格是行标题，其余是值。
    3. 如需 xlsx：GET /eps/checkDownload1.do?sheetId=...&sid=... 拿 sign，
       再 GET /eps/download.do?sheetId=&sid=&sign=&dataType=&exportType=&lang=
* 发码接口 /user/verify/getSign + /user/verify/sendCode 前面有阿里云滑块验证码，
  这里按“只走短信验证码登录”的要求：验证码由你在网页/手机上获取，脚本只负责最后
  那步 loginType=MOBILE 的登录 + 后续取数。
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import requests

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
except ImportError:  # pragma: no cover
    sys.exit("缺少依赖 cryptography，请先: pip install requests cryptography")

BASE = "https://olap.epsnet.com.cn"
DEFAULT_SID_FILE = Path(os.environ.get("EPS_SID_FILE", "~/.eps_sid")).expanduser()

# 前端 index-*.js 里写死的两段数：AES.decrypt(KEY, "addceffs") => b"1321321561321321"
_JS_KEY_B64 = (
    "U2FsdGVkX1+sA1gKG00U89ovJjaeAcSP3RxXwvlGNWM7yJiE1eeGq6s2zfp9UyHs"
)
_JS_PASSPHRASE = b"addceffs"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# 前端加解密
# --------------------------------------------------------------------------
def _evp_bytes_to_key(passphrase: bytes, salt: bytes, size: int = 48) -> bytes:
    """OpenSSL EVP_BytesToKey(MD5, 1 iteration)，CryptoJS 的 passphrase 模式同款。"""
    out = b""
    prev = b""
    while len(out) < size:
        prev = hashlib.md5(prev + passphrase + salt).digest()
        out += prev
    return out[:size]


def _cryptojs_passphrase_decrypt(b64_text: str) -> bytes:
    raw = base64.b64decode(b64_text)
    if raw[:8] != b"Salted__":
        raise ValueError("不是 CryptoJS OpenSSL 格式密文")
    salt, data = raw[8:16], raw[16:]
    # CryptoJS 的 passphrase 模式: AES-256(32B key) + 16B IV, 共 48B
    key_iv = _evp_bytes_to_key(_JS_PASSPHRASE, salt, 48)
    key, iv = key_iv[:32], key_iv[32:48]
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    pt = dec.update(data) + dec.finalize()
    return pt[: -pt[-1]]


AES_KEY = _cryptojs_passphrase_decrypt(_JS_KEY_B64)[:16]
AES_IV = _cryptojs_passphrase_decrypt(_JS_KEY_B64)[:16]


def decrypt_dataletBO(payload) -> dict:
    """解 dataletBO（getDimension / getDimensionList / searchDimension 等的密文字段）。"""
    if isinstance(payload, (dict, list)):
        return payload  # 已经是明文（center.do 的就是明文）
    raw = base64.b64decode(str(payload))
    dec = Cipher(algorithms.AES(AES_KEY), modes.CBC(AES_IV)).decryptor()
    pt = dec.update(raw) + dec.finalize()
    pt = pt[: -pt[-1]]
    return json.loads(pt.decode("utf-8"))


# --------------------------------------------------------------------------
# HTTP 客户端
# --------------------------------------------------------------------------
class ApiError(RuntimeError):
    def __init__(self, message: str, payload=None):
        super().__init__(message)
        self.payload = payload


class Client:
    def __init__(self, sid: str | None = None, lang: int = 1, timeout: int = 600,
                 debug: bool = False, min_interval: float = 0.8):
        self.sid = sid
        self.timeout = timeout
        self.debug = debug
        self.min_interval = min_interval
        self._last_req = 0.0
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "lang": str(lang),
            "Cache-Control": "no-cache",
            "Referer": BASE + "/",
            "Origin": BASE,
            "Accept": "application/json, text/plain, */*",
        })

    # -- 基础请求 ---------------------------------------------------------
    def _finish(self, resp: requests.Response):
        ct = resp.headers.get("content-type", "")
        if "json" in ct:
            try:
                return resp.json()
            except ValueError:
                return resp.text
        return resp

    def _check(self, data):
        if isinstance(data, dict) and data.get("success") is False:
            raise ApiError(data.get("message") or "接口返回失败", data)
        return data

    def _throttle(self):
        wait = self.min_interval - (time.time() - self._last_req)
        if wait > 0:
            time.sleep(wait)
        self._last_req = time.time()

    def _request(self, method: str, path: str, **kw):
        """带限速 + “操作过于频繁”退避重试的请求。"""
        params = kw.pop("params", {})
        params.setdefault("sid", self.sid)
        params = {k: v for k, v in params.items() if v is not None}
        if self.debug:
            print(f"[{method.upper():4}] {BASE}{path} {params}", file=sys.stderr)
        last = None
        for attempt in range(5):
            self._throttle()
            try:
                r = self.s.request(method, BASE + path, params=params, timeout=self.timeout,
                                   **kw)
                data = self._finish(r)
                if isinstance(data, dict) and data.get("success") is False:
                    msg = str(data.get("message") or "")
                    if ("频繁" in msg or "稍候" in msg) and attempt < 4:
                        time.sleep(2 * (attempt + 1))
                        last = data
                        continue
                    raise ApiError(msg or "接口返回失败", data)
                return data
            except requests.RequestException as ex:
                last = ex
                if attempt < 4:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        if isinstance(last, dict):
            raise ApiError(last.get("message") or "请求失败", last)
        raise ApiError(f"请求失败: {last}")

    def get(self, path: str, **params):
        return self._request("get", path, params=params)

    def post(self, path: str, json_body=None, data=None, **params):
        return self._request("post", path, params=params, json=json_body, data=data)

    # -- 登录（只走短信验证码 loginType=MOBILE） ---------------------------
    def login_sms(self, account: str, verify_code: str) -> dict:
        """手机号 + 短信验证码登录。

        GET /user/login/login?account=<手机号>&verifyCode=<验证码>&loginType=MOBILE
        成功返回 {"success":true,"sid":"...","userInfo":{...}}；sid 就是后续所有接口的凭证。

        验证码怎么来：平台的发码接口 (/user/verify/getSign + /sendCode) 前置了阿里云
        滑块验证码，脚本不做绕过；请在网页登录框点“获取验证码”（或手机上接收），
        把收到的验证码填进来。验证码有效期一般几分钟，登录完拿到 sid 即可长期复用。
        """
        j = self.get("/user/login/login", account=account,
                     verifyCode=verify_code, loginType="MOBILE")
        if not j.get("success") or not j.get("sid"):
            raise ApiError(j.get("message") or "短信登录失败", j)
        self.sid = j["sid"]
        return j

    def user_info(self) -> dict:
        if not self.sid:
            raise ApiError("没有 sid，先 login 或 --sid")
        return self.get("/user/login/userInfo")

    # -- 元数据 -----------------------------------------------------------
    def cube_tree(self) -> list:
        j = self.get("/eps/metaCube/listMetaCubeTree.do")
        return j.get("list") or []

    def all_cubes(self) -> list:
        """一次性拿全库列表（约 900+ 条，一次返回，不分页）。"""
        j = self.get("/eps/metaCube/listMetaCube.do", currentPage=1)
        return j.get("list") or []

    def cube_detail(self, cube_id: int) -> dict:
        j = self.get("/eps/metaCube/getMetaCube.do", cubeId=cube_id)
        return j.get("metaCube") or j

    def get_sheet(self, cube_id: int) -> dict:
        """取某库的查询条件（已解密），含 sheetId / 维度布局 / 维度成员树。"""
        if not self.sid:
            raise ApiError("getDimension 需要登录：先 login，或把浏览器里的 sid 传给 --sid")
        j = self.get("/eps/getDimension.do", cubeId=cube_id)
        bo = decrypt_dataletBO(j["dataletBO"])
        bo["_raw"] = {k: v for k, v in j.items() if k != "dataletBO"}
        return bo

    def dim_children(self, sheet_id: str, dim_type: str, parent_code: str = "") -> list:
        j = self.get("/eps/getDimensionList.do", sheetId=sheet_id, dimType=dim_type,
                     parentCode=parent_code)
        return decrypt_dataletBO(j.get("dimensionList") or [])

    def dim_all_codes(self, sheet_id: str, dim_type: str) -> list:
        j = self.get("/eps/getDimensionAll.do", sheetId=sheet_id, dimType=dim_type)
        lst = j.get("dimensionCodeList") or []
        return [x.get("dimCode") if isinstance(x, dict) else str(x) for x in lst]

    # -- 取数 -------------------------------------------------------------
    def query(self, cube_id: int, sheet_id: str, dims: dict,
              meta_columns: list, meta_rows: list, fix: list,
              controls: dict | None = None) -> dict:
        ctl = controls or DEFAULT_CONTROLS
        body = {
            "cubeId": cube_id,
            "sheetId": sheet_id,
            "dims": json.dumps(
                [{"codeName": k, "codes": list(map(str, v))} for k, v in dims.items()],
                ensure_ascii=False,
            ),
            "metaColumns": "-".join(map(str, meta_columns)),
            "metaRows": "-".join(map(str, meta_rows)),
            "fix": "-".join(map(str, fix)),
        }
        for k in ("s1", "s2", "s3", "s4", "s5"):
            body[k] = ctl.get(k)
        j = self.post("/eps/center.do", json_body=body)
        bo = j.get("dataletBO")
        if isinstance(bo, str):
            bo = decrypt_dataletBO(bo)
        if not bo:
            raise ApiError(j.get("message") or "查询无结果", j)
        return bo

    # -- 下载 -------------------------------------------------------------
    def check_download(self, sheet_id: str) -> dict:
        return self.get("/eps/checkDownload1.do", sheetId=sheet_id)

    def download(self, sheet_id: str, sign: str, out: Path,
                 data_type: int = 2, export_type: str = "XLSX") -> Path:
        params = {
            "sheetId": sheet_id,
            "sid": self.sid,
            "sign": sign,
            "dataType": data_type,
            "exportType": export_type,
            "lang": 1,
        }
        r = self.s.get(BASE + "/eps/download.do", params=params, timeout=self.timeout,
                       stream=True)
        ct = r.headers.get("content-type", "")
        if "json" in ct or "html" in ct:
            raise ApiError(f"下载失败：{r.text[:300]}")
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "wb") as fh:
            for chunk in r.iter_content(65536):
                fh.write(chunk)
        return out


DEFAULT_CONTROLS = {
    "s1": {"dealStr": "empty"},
    "s2": {"method": "", "type": ""},
    "s3": {"index8020": "", "fontStyle8020": "", "bgColor8020": ""},
    "s4": {"orderStr": "", "index": ""},
    "s5": {"dealStr": "", "showBackColor": "", "showFontStyle": ""},
}


# --------------------------------------------------------------------------
# dataletBO -> 表格
# --------------------------------------------------------------------------
def _dim_code(x) -> str:
    if isinstance(x, dict):
        return str(x.get("codeName") or x.get("name") or "")
    return str(x)


def _cell(c):
    if isinstance(c, dict):
        v = c.get("showValue", "")
        return "" if v is None else v
    return "" if c is None else c


def parse_table(bo: dict) -> dict:
    """把 dataletBO 解析成：表头行 + 数据行 + 维度名。

    cellBOs 布局：前 len(metaTops) 行是表头，之后每行前 len(metaLefts) 格是行标题。
    """
    tops = [_dim_code(x) for x in (bo.get("metaTops") or [])]
    lefts = [_dim_code(x) for x in (bo.get("metaLefts") or [])]
    cells = bo.get("cellBOs") or []
    grid = [[_cell(c) for c in (row or [])] for row in cells]
    width = max((len(r) for r in grid), default=0)
    grid = [r + [""] * (width - len(r)) for r in grid]
    n_top, n_left = len(tops), len(lefts)
    return {
        "metaTops": tops,
        "metaLefts": lefts,
        "header": grid[:n_top],
        "data": grid[n_top:],
        "width": width,
        "n_left": n_left,
        "dataCount": bo.get("dataCount"),
        "sheetId": bo.get("sheetId"),
        "dimensionNameMap": bo.get("dimensionNameMap") or {},
    }


def write_grid_csv(path: Path, table: dict) -> None:
    """按网页上看到的表样子写 CSV（带表头行）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        for row in table["header"]:
            w.writerow(row)
        for row in table["data"]:
            w.writerow(row)


def write_xlsx(path: Path, table: dict) -> None:
    """写 xlsx：宽表 + 长表两个 sheet（需要 openpyxl）。"""
    try:
        from openpyxl import Workbook
    except ImportError:
        raise SystemExit("缺少 openpyxl，先 pip install openpyxl")
    path.parent.mkdir(parents=True, exist_ok=True)
    n_left, width = table["n_left"], table["width"]
    name_map = table["dimensionNameMap"]

    def num(v):
        if isinstance(v, (int, float)):
            return v
        t = str(v).strip()
        try:
            f = float(t)
            return f
        except ValueError:
            return v

    wb = Workbook()
    ws = wb.active
    ws.title = "宽表"
    for row in table["header"]:
        ws.append(row)
    for row in table["data"]:
        ws.append([row[j] if j < n_left else num(row[j]) for j in range(width)])

    ws2 = wb.create_sheet("长表")
    left_names = [name_map.get(c, c) for c in table["metaLefts"]]
    titles = []
    for j in range(width):
        labels = [str(h[j]) for h in table["header"]
                  if j < len(h) and str(h[j]).strip() != ""]
        titles.append(" | ".join(labels))
    ws2.append(left_names + ["column", "value"])
    for row in table["data"]:
        for j in range(n_left, width):
            ws2.append(list(row[:n_left]) + [titles[j], num(row[j])])
    wb.save(path)


def write_long_csv(path: Path, table: dict) -> None:
    """长表：行维度值 + 列标题 + 数值，方便 pandas 直接用。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    n_left, width = table["n_left"], table["width"]
    name_map = table["dimensionNameMap"]
    left_names = [name_map.get(c, c) for c in table["metaLefts"]]

    titles = []
    for j in range(width):
        labels = [
            str(h[j]) for h in table["header"]
            if j < len(h) and str(h[j]).strip() != ""
        ]
        titles.append(" | ".join(labels))

    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(left_names + ["column"] + ["value"])
        for row in table["data"]:
            row_labels = list(row[:n_left])
            for j in range(n_left, width):
                w.writerow(row_labels + [titles[j], row[j]])


# --------------------------------------------------------------------------
# 选择解析
# --------------------------------------------------------------------------
def load_selection(args) -> dict:
    if args.select:
        data = json.loads(Path(args.select).read_text(encoding="utf-8"))
    elif args.dims:
        data = {"dims": json.loads(args.dims)}
    elif getattr(args, "all", False):
        data = {"dims": {}}
    else:
        raise SystemExit("需要 --dims '<json>' 或 --select <json文件>（也可以只用 --all 选全量）")
    dims = data.get("dims") or {}
    if args.all:
        dims = dict(dims)
    return {
        "dims": dims,
        "metaColumns": data.get("metaColumns") or data.get("metaColumn"),
        "metaRows": data.get("metaRows") or data.get("metaRow"),
        "fix": data.get("fix") or data.get("metaFixed"),
        "controls": data.get("controls"),
    }


def resolve_layout(bo: dict, sel: dict) -> dict:
    lefts = [c for c in (_dim_code(x) for x in (bo.get("metaLefts") or [])) if c]
    tops = [c for c in (_dim_code(x) for x in (bo.get("metaTops") or [])) if c]
    fixeds = [c for c in (_dim_code(x) for x in (bo.get("fixeds") or bo.get("metaFixeds") or [])) if c]
    layout = {
        "metaColumns": sel.get("metaColumns") or lefts,
        "metaRows": sel.get("metaRows") or tops,
        "fix": sel.get("fix") if sel.get("fix") is not None else fixeds,
    }
    dim_names = [c for c in (_dim_code(d) for d in
                 ((bo.get("allDimensions") or {}).get("dimensionVOList") or [])) if c]
    covered = layout["metaColumns"] + layout["metaRows"] + layout["fix"]
    missing = [d for d in dim_names if d and d not in covered]
    if missing:
        raise SystemExit(
            "这些维度没放进行/列/固定里: %s\n当前布局: 行(会变成表头列?) metaColumns=%s, "
            "metaRows=%s, fix=%s\n请在 --dims/--select 里同时给出 metaColumns / metaRows / fix"
            % (missing, layout["metaColumns"], layout["metaRows"], layout["fix"])
        )
    return layout


def resolve_dims(client: Client, bo: dict, sel: dict, allow_all: bool) -> dict:
    sheet_id = bo.get("sheetId") or bo.get("_raw", {}).get("sheetId")
    dim_names = [c for c in (_dim_code(d) for d in
                 ((bo.get("allDimensions") or {}).get("dimensionVOList") or [])) if c]
    given = {k: (v if isinstance(v, list) else [v]) for k, v in (sel.get("dims") or {}).items()}
    out: dict = {}
    for name in dim_names:
        if not name:
            continue
        codes = given.get(name)
        if codes is None:
            if not allow_all:
                need = [d for d in dim_names if d not in given]
                raise SystemExit("还缺这些维度的值: %s（可先运行 dims 子命令看代码，"
                                 "或加 --all 用全量）" % need)
            codes = client.dim_all_codes(sheet_id, name)
            print(f"[warn] {name} 未指定，已用全量 {len(codes)} 个代码", file=sys.stderr)
        if codes == ["*"] or codes == "*":
            codes = client.dim_all_codes(sheet_id, name)
        out[name] = [str(c) for c in codes]
    return out


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def first_data_code(client: Client, sheet_id: str, dim_type: str,
                    nodes=None, depth: int = 0) -> str | None:
    """在维度树里找第一个能查的代码（IS_VAL=1 / isEnd=1），用于 quota 的最小查询。"""
    for n in nodes or []:
        if not isinstance(n, dict):
            continue
        if n.get("IS_VAL") == 1 or n.get("isEnd") == 1 or n.get("IS_END") == 1:
            return str(n.get("dimCode"))
    if depth >= 3:
        return None
    for n in nodes or []:
        if isinstance(n, dict) and n.get("dimCode"):
            kids = client.dim_children(sheet_id, dim_type, str(n["dimCode"]))
            found = first_data_code(client, sheet_id, dim_type, kids, depth + 1)
            if found:
                return found
    return None


def get_sid(args) -> str | None:
    sid = getattr(args, "sid", None) or os.environ.get("EPS_SID")
    if not sid and DEFAULT_SID_FILE.exists():
        try:
            sid = json.loads(DEFAULT_SID_FILE.read_text()).get("sid")
        except Exception:
            sid = DEFAULT_SID_FILE.read_text().strip()
    return sid


def save_sid(sid: str) -> None:
    DEFAULT_SID_FILE.write_text(json.dumps({"sid": sid, "saved_at": int(time.time())}))
    try:
        DEFAULT_SID_FILE.chmod(0o600)
    except OSError:
        pass


def print_dims_tree(nodes, indent=2, depth=0, max_depth=2, max_items=40):
    pad = " " * indent
    for i, n in enumerate(nodes or []):
        if i >= max_items:
            print(f"{pad}... 还有 {len(nodes) - max_items} 个")
            break
        if not isinstance(n, dict):
            print(f"{pad}{n}")
            continue
        code = n.get("dimCode") or n.get("code") or ""
        name = n.get("dimName") or n.get("name") or ""
        print(f"{pad}- {code}  {name}".rstrip())
        kids = n.get("objList") or n.get("children") or []
        if kids and depth < max_depth:
            print_dims_tree(kids, indent + 2, depth + 1, max_depth, max_items)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="EPS数据平台 (olap.epsnet.com.cn) 接口客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--sid", help="登录后的 sid（也可用环境变量 EPS_SID 或 ~/.eps_sid）")
    p.add_argument("--lang", type=int, default=1, help="1=中文 2=英文")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--debug", action="store_true", help="打印每个请求")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("login", help="手机短信验证码登录并保存 sid")
    sp.add_argument("--account", required=True, help="手机号")
    sp.add_argument("--code", help="短信验证码；不填则交互输入")

    sub.add_parser("whoami", help="验证 sid 对应的用户信息")

    sub.add_parser("tree", help="九个研究系列（顶层库目录）")

    sp = sub.add_parser("cubes", help="库列表（公开接口，不需登录）")
    sp.add_argument("--filter", help="按名称/全名模糊过滤")
    sp.add_argument("--out", help="另存为 JSON")

    sp = sub.add_parser("dims", help="某库的维度布局与成员代码（需登录）")
    sp.add_argument("--cube", type=int, required=True)
    sp.add_argument("--deep", action="store_true", help="继续展开一层成员树")
    sp.add_argument("--deep-api", action="store_true",
                    help="通过 getDimensionList.do 逐层抓取（慢，但完整）")
    sp.add_argument("--out", help="把解密后的结构存成 JSON")

    sp = sub.add_parser("quota", help="查每日下载次数 / 今日已用 / 单次限制（不消耗下载次数）")
    sp.add_argument("--cube", type=int, default=891)
    sp.add_argument("--dims", help="自定义最小查询的代码，如 '{\"time\":[\"2024010101\"],\"indicator\":[\"01010103\"]}'")

    sp = sub.add_parser("dimtree", help="递归打印维度成员树（找叶子指标代码用，需登录）")
    sp.add_argument("--cube", type=int, required=True)
    sp.add_argument("--dim", help="维度 codeName，如 indicator / time；不填则打印全部")
    sp.add_argument("--parent", default="", help="从哪个成员开始往下（默认根）")
    sp.add_argument("--depth", type=int, default=4)
    sp.add_argument("--out", help="把整棵树存成 JSON")

    for name, help_text in (("query", "取数并输出 CSV"), ("download", "取数并下载平台 Excel/CSV")):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--cube", type=int, required=True)
        sp.add_argument("--dims", help="JSON: {\"time\":[\"2024\"],\"indicator\":[\"A0101\"]}")
        sp.add_argument("--select", help="JSON 文件: {dims, metaColumns, metaRows, fix}")
        sp.add_argument("--all", action="store_true", help="未给出的维度用全量代码")
        sp.add_argument("--max-cells", type=int, default=50000)
        if name == "query":
            sp.add_argument("--out", default="eps_data.csv", help="输出 CSV")
            sp.add_argument("--long", help="另外输出长表 CSV")
            sp.add_argument("--xlsx", help="另外输出 Excel（宽表+长表两个 sheet）")
            sp.add_argument("--raw", help="保存 center.do 原始返回 JSON")
            sp.add_argument("--no-grid", action="store_true", help="不写宽表 CSV")
        else:
            sp.add_argument("--out", default="eps_data.xlsx")
            sp.add_argument("--export-type", default="XLSX",
                            choices=["XLSX", "XLS", "CSV", "PDF", "DTA", "TXT"])
            sp.add_argument("--data-type", type=int, default=2)
            sp.add_argument("--no-check", action="store_true", help="跳过 checkDownload1")

    args = p.parse_args(argv)
    client = Client(sid=get_sid(args), lang=args.lang, timeout=args.timeout,
                    debug=args.debug)

    try:
        if args.cmd == "login":
            code = args.code or input("请输入手机收到的短信验证码: ").strip()
            j = client.login_sms(args.account, code)
            save_sid(client.sid)
            ui = j.get("userInfo") or {}
            print(json.dumps({
                "sid": client.sid,
                "saved_to": str(DEFAULT_SID_FILE),
                "user": {k: ui.get(k) for k in
                         ("userId", "userName", "realname", "groupId", "groupName",
                          "endDate") if k in ui},
            }, ensure_ascii=False, indent=2))
            print("\n提示: sid 会过期；失效后重新 login 即可。", file=sys.stderr)
            return 0

        if args.cmd == "whoami":
            print(json.dumps(client.user_info(), ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "tree":
            for it in client.cube_tree():
                print(f"{it.get('cubeId'):>8}  {it.get('cubeNameZh')}  "
                      f"(pid={it.get('pid')}, total={it.get('totalNum')})")
            return 0

        if args.cmd == "cubes":
            items = client.all_cubes()
            if args.filter:
                f = args.filter.lower()
                items = [x for x in items
                         if f in str(x.get("cubeNameZh", "")).lower()
                         or f in str(x.get("cubeFnameZh", "")).lower()
                         or f in str(x.get("descZh", "")).lower()]
            print(f"# {len(items)} 个库")
            print(f"{'cubeId':>8}  {'名称':<22} {'全名':<40} 更新时间")
            for x in items:
                print(f"{x.get('cubeId'):>8}  {str(x.get('cubeNameZh',''))[:22]:<22} "
                      f"{str(x.get('cubeFnameZh',''))[:40]:<40} {x.get('lstmodDate','')}")
            if args.out:
                Path(args.out).write_text(json.dumps(items, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
                print(f"\n已保存: {args.out}")
            return 0

        if args.cmd == "dims":
            bo = client.get_sheet(args.cube)
            if args.out:
                Path(args.out).write_text(json.dumps(bo, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
                print(f"解密后的结构已保存: {args.out}")
            name_map = bo.get("dimensionNameMap") or {}
            lefts = [_dim_code(x) for x in (bo.get("metaLefts") or [])]
            tops = [_dim_code(x) for x in (bo.get("metaTops") or [])]
            fixeds = [_dim_code(x) for x in (bo.get("fixeds") or bo.get("metaFixeds") or [])]
            cube = bo.get("cube") or {}
            print(f"库: {args.cube} {cube.get('cubeNameZh','')}")
            print(f"sheetId: {bo.get('sheetId')}   freqId: {bo.get('freqId')}")
            print(f"行维度(metaLefts): {lefts}")
            print(f"列维度(metaTops) : {tops}")
            print(f"固定维度(fixeds) : {fixeds}")
            print("提示: 查询用的 codes 是成员节点的 dimCode（如 time=2024010101、"
                  "indicator=01010103）；")
            print("      dimtree 里标 [数据] 的才有数据，[目录] 只是分类、查不出数。")
            print("\n维度列表:")
            for d in ((bo.get("allDimensions") or {}).get("dimensionVOList") or []):
                code = _dim_code(d)
                label = name_map.get(code) or d.get("dimName") or ""
                kids = d.get("objList") or []
                print(f"- {code:<14} {label}  顶层成员 {len(kids)} 个"
                      + (f"  维度ID={d.get('dimensionId')}" if d.get("dimensionId") else ""))
                if kids:
                    print_dims_tree(kids, indent=2,
                                    max_depth=(2 if args.deep else 0))
                if args.deep_api:
                    sheet_id = bo.get("sheetId")
                    print_dims_tree(client.dim_children(sheet_id, code),
                                    indent=2, max_depth=1, max_items=20)
            return 0

        if args.cmd == "quota":
            bo = client.get_sheet(args.cube)
            sh = bo.get("sheetId")
            layout = resolve_layout(bo, {"dims": {}})
            if args.dims:
                dims = {k: [str(x) for x in v] for k, v in json.loads(args.dims).items()}
            else:
                dims = {}
                for d in (bo.get("allDimensions") or {}).get("dimensionVOList") or []:
                    name = _dim_code(d)
                    if name:
                        code = first_data_code(client, sh, name, d.get("objList") or [])
                        if code:
                            dims[name] = [code]
                # 自动选到的“第一个有值代码”不一定真有数据，891 用已知可用的 GDP
                if args.cube == 891:
                    dims["indicator"] = ["01010103"]
            datalet = client.query(args.cube, sh, dims, layout["metaColumns"],
                                   layout["metaRows"], layout["fix"])
            if not (datalet.get("cellBOs") or []):
                raise SystemExit(
                    "自动选的最小查询没有数据，请用 --dims 指定一组能查出来的代码，例如：\n"
                    "  --dims '{\"time\":[\"2024010101\"],\"indicator\":[\"01010103\"]}'")
            j = client.check_download(sh)
            ui = client.user_info().get("userInfo") or {}
            cube_meta = next((x for x in (ui.get("metaCubeList") or [])
                              if str(x.get("cubeId")) == str(args.cube)), {})
            total = j.get("downloadCount")
            used = j.get("todayDownloadCount")
            print(json.dumps({
                "cube": args.cube,
                "每日下载次数上限": total,
                "今日已用": used,
                "今日剩余": (total - used) if isinstance(total, int)
                and isinstance(used, int) else None,
                "单次查询上限(格)": cube_meta.get("querySize"),
                "单次下载最大行数(maxRows)": j.get("maxRows"),
                "分批大小(partSize)": j.get("partSize"),
                "本次数据行数": j.get("nowDownloadSize"),
                "可否下载": j.get("canDownload"),
                "超限": j.get("overLimit"),
            }, ensure_ascii=False, indent=2))
            return 0

        if args.cmd == "dimtree":
            bo = client.get_sheet(args.cube)
            sheet_id = bo.get("sheetId")
            dvo = (bo.get("allDimensions") or {}).get("dimensionVOList") or []
            dims = [d for d in dvo if not args.dim or d.get("codeName") == args.dim]
            if not dims:
                raise SystemExit(f"没有维度 {args.dim}，可选: "
                                 f"{[d.get('codeName') for d in dvo]}")
            export = {}

            def walk(parent_code, depth, pad, store):
                if depth > args.depth:
                    return
                for node in client.dim_children(sheet_id, store["dim"], parent_code):
                    code = node.get("dimCode")
                    has_val = (node.get("IS_VAL") == 1 or node.get("isEnd") == 1
                               or node.get("IS_END") == 1)
                    print(f"{pad}{code:<12} {node.get('dimName','')}"
                          + ("  [数据]" if has_val else "  [目录]"))
                    store["tree"].append(node)
                    if node.get("isParent") or node.get("IS_VAL") == 0:
                        walk(code, depth + 1, pad + "  ", store)

            for d in dims:
                name = d.get("codeName")
                print(f"# 维度 {name}（{name}）")
                store = {"dim": name, "tree": []}
                walk(args.parent, 1, "  ", store)
                export[name] = store["tree"]
            if args.out:
                Path(args.out).write_text(
                    json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"\n已保存: {args.out}")
            return 0

        # ---- query / download 共用：取 sheet、解析选择、查数 ----
        if args.cmd in ("query", "download"):
            bo = client.get_sheet(args.cube)
            sel = load_selection(args)
            layout = resolve_layout(bo, sel)
            dims = resolve_dims(client, bo, sel, allow_all=args.all)
            n_cells = 1
            for v in dims.values():
                n_cells *= max(len(v), 1)
            if n_cells > args.max_cells:
                print(f"[warn] 预计 {n_cells} 个数据格，超过 --max-cells={args.max_cells}；"
                      f"平台单次查询通常上限 5000~5 万格，建议缩小范围", file=sys.stderr)
            sheet_id = bo.get("sheetId")
            print(f"[i] cube={args.cube} sheetId={sheet_id} 布局: 行={layout['metaColumns']} "
                  f"列={layout['metaRows']} 固定={layout['fix']}", file=sys.stderr)
            datalet = client.query(args.cube, sheet_id, dims,
                                   layout["metaColumns"], layout["metaRows"],
                                   layout["fix"], controls=sel.get("controls"))
            table = parse_table(datalet)
            print(f"[i] 返回 {len(table['data'])} 行 x {table['width']} 列, "
                  f"dataCount={table['dataCount']}", file=sys.stderr)

            if args.cmd == "query":
                if args.raw:
                    Path(args.raw).write_text(
                        json.dumps(datalet, ensure_ascii=False, indent=2), encoding="utf-8")
                    print(f"已保存原始返回: {args.raw}")
                if not args.no_grid:
                    write_grid_csv(Path(args.out), table)
                    print(f"已写入宽表: {args.out}")
                if args.long:
                    write_long_csv(Path(args.long), table)
                    print(f"已写入长表: {args.long}")
                if args.xlsx:
                    write_xlsx(Path(args.xlsx), table)
                    print(f"已写入 Excel: {args.xlsx}")
                return 0

            # download
            if not args.no_check:
                cj = client.check_download(sheet_id)
                ok = cj.get("success") or cj.get("canDownload")
                if not ok:
                    raise ApiError(f"下载校验未通过: {cj.get('message')}", cj)
                if cj.get("noData"):
                    raise ApiError("平台说该条件没有数据", cj)
                sign = cj.get("sign")
            else:
                sign = ""
            out = client.download(sheet_id, sign, Path(args.out),
                                  data_type=args.data_type,
                                  export_type=args.export_type)
            print(f"已下载: {out} ({out.stat().st_size} 字节)")
            return 0

        raise SystemExit(f"未知命令 {args.cmd}")

    except ApiError as e:
        print(f"接口错误: {e}", file=sys.stderr)
        if e.payload:
            print(json.dumps(e.payload, ensure_ascii=False)[:2000], file=sys.stderr)
        return 2
    except requests.RequestException as e:
        print(f"网络错误: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
