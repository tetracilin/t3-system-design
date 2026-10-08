"""Create a NEW project in Teable and fill it with generated test data.

    python scripts/make_test_project.py --name TEST_Phao_Thuy_Am_Demo --home %APPDATA%\t3desk-test

It uses the Teable address and token your app already has, creates a new base in the same space (or reuses an empty one
with --base-id), bootstraps the 16 tables, then writes the data as drafts and sends them with the normal Commit, so
validation, ordering and the first-come ID rule all apply.

It works in its OWN app folder (--home), never in the folder of your real work: drafts are kept per folder, not per base,
so loading a test project into the folder that holds your own unsent drafts would send those drafts to the wrong project.
The script refuses to run if that folder already has drafts. To look at the result, start the app with the same folder:
    set T3DESK_HOME=%APPDATA%\t3desk-test && run.bat --browser
Run it once per project name: without --base-id a second run makes a second base.

Shape of the data: 2 architectures, 3 nodes each, 3 sub-nodes under each node, 2 specifications on each sub-node
(2 x 3 x 3 x 2 = 36 specifications), plus what the rules expect around them: requirements, allocations, a library item for
every node (three parts are shared by both architectures) and the two tree gates closed.
Stop the app first: the script and the app share one local database.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from t3desk import server  # noqa: E402

OEM, SELF, ASSY = "Mua OEM", "Tự chế tạo", "Cụm"
DONE, FILLING, HOLD = "Đã điền", "Đang điền", "Chỗ giữ chỗ"
JUNIORS = ["binh", "chi", "dung", "em", "gia", "hoa"]

REQUIREMENTS = [
    ("R1", "Thu tín hiệu âm dải 10 Hz đến 20 kHz", "Quét tần 10 Hz - 20 kHz, sai lệch biên độ dưới 3 dB"),
    ("R2", "Độ nhạy thu tối thiểu -180 dB re 1V/µPa", "Đo trong bể chuẩn tại 1 kHz"),
    ("R3", "Làm việc ở độ sâu đến 300 m", "Thử áp 1,5 lần trong 4 giờ, không rò"),
    ("R4", "Khối lượng toàn hệ không quá 25 kg", "Cân toàn hệ sau lắp ráp"),
    ("R5", "Hoạt động liên tục tối thiểu 72 giờ", "Chạy thử 72 giờ ở 25 độ C"),
    ("R6", "Truyền dữ liệu về trạm xa tối thiểu 10 km", "Thử ngoài trời, tỷ lệ mất gói dưới 5 %"),
]

# architecture -> (name, principle, [(sub-system, [components])])
ARCHITECTURES = {
    "KT-A": ("Phao trôi một hydrophone", "Một hydrophone treo dưới phao trôi, xử lý và ghi tại chỗ",
             [("Cảm biến", ["Hydrophone HTI-96", "Tiền khuếch đại", "Bộ lọc thông dải"]),
              ("Xử lý và ghi dữ liệu", ["Bo ADC 24-bit", "Vi xử lý ARM", "Thẻ nhớ công nghiệp"]),
              ("Nguồn và vỏ", ["Pin lithium 24V", "Vỏ chịu áp", "Mạch quản lý nguồn"])]),
    "KT-B": ("Phao dây mảng hydrophone", "Mảng tám hydrophone trên dây, truyền dữ liệu về trạm",
             [("Mảng cảm biến", ["Hydrophone HTI-96", "Dây mảng 8 kênh", "Hộp nối kín nước"]),
              ("Xử lý và truyền tin", ["Bo ADC 24-bit", "Modem vô tuyến", "Ăng-ten"]),
              ("Nguồn và phao nổi", ["Pin lithium 24V", "Phao nổi", "Dây neo"])]),
}

# component -> (kind, status, maker, model, sku, assignee)   assignee None = nobody asked yet
COMPONENTS: dict[str, tuple[str, str, str, str, str, str | None]] = {
    "Hydrophone HTI-96": (OEM, DONE, "Hãng Thử A", "HTI-96-MIN", "SKU-96", "an"),
    "Tiền khuếch đại": (SELF, HOLD, "", "", "", "binh"),
    "Bộ lọc thông dải": (SELF, HOLD, "", "", "", None),
    "Bo ADC 24-bit": (OEM, DONE, "Hãng Thử B", "ADC-24-8", "SKU-ADC24", "an"),
    "Vi xử lý ARM": (OEM, DONE, "Hãng Thử C", "ARM-M7-600", "SKU-M7", "chi"),
    "Thẻ nhớ công nghiệp": (OEM, FILLING, "Hãng Thử D", "", "", "dung"),
    "Pin lithium 24V": (OEM, DONE, "Hãng Thử E", "LI-24-150", "SKU-LI24", "an"),
    "Vỏ chịu áp": (SELF, FILLING, "", "", "", "em"),
    "Mạch quản lý nguồn": (SELF, DONE, "", "", "", "gia"),
    "Dây mảng 8 kênh": (SELF, DONE, "", "", "", "hoa"),
    "Hộp nối kín nước": (SELF, FILLING, "", "", "", "dung"),
    "Modem vô tuyến": (OEM, DONE, "Hãng Thử F", "RF-900", "SKU-RF9", "chi"),
    "Ăng-ten": (OEM, DONE, "Hãng Thử G", "ANT-9-3", "SKU-ANT", "chi"),
    "Phao nổi": (SELF, DONE, "", "", "", "em"),
    "Dây neo": (SELF, HOLD, "", "", "", "chi"),
}

# component -> two specifications (name, min, max, unit, requirement or None for a derived one)
SPECS: dict[str, list[tuple[str, float | None, float | None, str, str | None]]] = {
    "Hydrophone HTI-96": [("Độ nhạy", -200, -170, "dB re 1V/µPa", "R2"), ("Điện dung", 8, 14, "nF", None)],
    "Tiền khuếch đại": [("Độ lợi", 20, 40, "dB", "R2"), ("Nhiễu quy đổi đầu vào", None, 5, "nV/√Hz", None)],
    "Bộ lọc thông dải": [("Băng thông", 10, 20000, "Hz", "R1"), ("Độ suy giảm ngoài băng", 40, None, "dB", None)],
    "Bo ADC 24-bit": [("Độ phân giải", 24, None, "bit", "R1"), ("Tần số lấy mẫu", 48, None, "kHz", None)],
    "Vi xử lý ARM": [("Công suất tiêu thụ", None, 1.5, "W", "R5"), ("Xung nhịp", 400, None, "MHz", None)],
    "Thẻ nhớ công nghiệp": [("Dung lượng", 64, None, "GB", "R5"), ("Nhiệt độ làm việc", -20, 70, "°C", None)],
    "Pin lithium 24V": [("Dung lượng", 150, None, "Wh", "R5"), ("Khối lượng", None, 6, "kg", "R4")],
    "Vỏ chịu áp": [("Áp suất làm việc", 30, None, "bar", "R3"), ("Khối lượng", None, 8, "kg", "R4")],
    "Mạch quản lý nguồn": [("Hiệu suất", 90, None, "%", "R5"), ("Dòng chờ", None, 2, "mA", None)],
    "Dây mảng 8 kênh": [("Số kênh", 8, None, "kênh", "R1"), ("Độ sâu làm việc", 300, None, "m", "R3")],
    "Hộp nối kín nước": [("Cấp bảo vệ", 68, None, "IP", "R3"), ("Số cổng", 8, None, "cổng", None)],
    "Modem vô tuyến": [("Tốc độ dữ liệu", 9.6, None, "kbps", "R6"), ("Công suất phát", None, 2, "W", None)],
    "Ăng-ten": [("Tầm phủ sóng", 10, None, "km", "R6"), ("Khối lượng", None, 1, "kg", "R4")],
    "Phao nổi": [("Lực nổi dư", 15, None, "kg", None), ("Khối lượng", None, 7, "kg", "R4")],
    "Dây neo": [("Tải kéo đứt", 500, None, "kg", None), ("Độ sâu làm việc", 300, None, "m", "R3")],
}
LEADS = ["an", "binh", "chi"]


def build() -> list[tuple[str, dict[str, Any]]]:
    """Every record of the project, as (table, fields), in the order a person would enter them."""
    out: list[tuple[str, dict[str, Any]]] = []
    items: dict[str, str] = {}

    def item(name: str, cap: str, kind: str, status: str, owner: str | None, hang: str = "", model: str = "", sku: str = "") -> str:
        if name in items:
            return items[name]
        key = f"HM-{len(items) + 1:03d}"
        items[name] = key
        fields = {"ma_hm": key, "ten": name, "cap": cap, "loai": kind, "trang_thai": status, "ghi_chu": "Dữ liệu thử"}
        for k, v in (("nguoi_dien", owner), ("hang", hang), ("model", model), ("sku", sku)):
            if v:
                fields[k] = v
        out.append(("hang_muc", fields))
        return key

    for code, text, criterion in REQUIREMENTS:
        out.append(("yeu_cau", {"ma_yc": code, "mo_ta": text, "tieu_chi_nghiem_thu": criterion, "muc": "Bắt buộc",
                                "uu_tien": "H", "nguon": "Dữ liệu thử", "trang_thai": "Đã chốt"}))
    scores = {"KT-A": (4, 3, 4), "KT-B": (5, 3, 2)}
    for ma, (name, principle, subs) in ARCHITECTURES.items():
        tech, supply, schedule = scores[ma]
        out.append(("kien_truc", {"ma_kt": ma, "ten": name, "nguyen_ly": principle, "he_con_cap1": "; ".join(s for s, _ in subs),
                                  "yc_then_chot": "R1;R2", "diem_ky_thuat": tech, "diem_nguon_hang": supply,
                                  "diem_thoi_gian": schedule, "trang_thai": "Đề xuất"}))

    root_item = item("Hệ thống phao thủy âm", "Hệ thống", "Hệ thống", DONE, "an")
    out.append(("nut", {"ma_nut": "N0", "ma_hm": root_item, "so_luong": 1, "phu_trach": "an"}))

    spec_no, alloc_no, leaf_no, node_no = 0, 0, 0, 0
    for ma, (_, _, subs) in ARCHITECTURES.items():
        for sub_index, (sub_name, components) in enumerate(subs):
            node_no += 1
            parent = f"N{node_no}"
            sub_item = item(sub_name, "Hệ con", ASSY, FILLING, LEADS[sub_index])
            out.append(("nut", {"ma_nut": parent, "ma_cha": "N0", "ma_hm": sub_item, "ma_kt": ma, "so_luong": 1,
                                "phu_trach": LEADS[sub_index]}))
            for comp_index, comp in enumerate(components):
                kind, status, hang, model, sku, owner = COMPONENTS[comp]
                comp_item = item(comp, "Linh kiện", kind, status, owner, hang, model, sku)
                code = f"{parent}.{comp_index + 1}"
                leaf_no += 1
                out.append(("nut", {"ma_nut": code, "ma_cha": parent, "ma_hm": comp_item, "ma_kt": ma, "so_luong": 1,
                                    "phu_trach": JUNIORS[leaf_no % len(JUNIORS)]}))
                for name, low, high, unit, req in SPECS[comp]:
                    spec_no += 1
                    spec: dict[str, Any] = {"ma_ts": f"TS-{spec_no:03d}", "ma_nut": code, "ma_yc_goc": req or "Dẫn xuất",
                                            "thong_so": name, "kieu": "Số", "don_vi": unit, "kiem_chung": "Thử nghiệm",
                                            "muc": "Bắt buộc" if req else "Mong muốn"}
                    if low is not None:
                        spec["gia_tri_min"] = low
                    if high is not None:
                        spec["gia_tri_max"] = high
                    out.append(("thong_so", spec))
                    if req:
                        alloc_no += 1
                        out.append(("phan_bo", {"ma_pb": f"PB-{alloc_no:03d}", "ma_yc": req, "ma_nut": code, "kieu": "Mỗi nút phải đạt"}))
    return out


def post(app: server.App, path: str, body: dict[str, Any]) -> dict[str, Any]:
    status, data = app.dispatch("POST", path, {}, body)
    if status != 200:
        raise SystemExit(f"{path} failed ({status}): {data}")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--name", required=True, help="name of the new project and its base")
    parser.add_argument("--home", required=True, help="app folder for this test project (NOT your real one)")
    parser.add_argument("--base-id", help="reuse this existing, empty, bootstrapped base instead of creating one")
    parser.add_argument("--space-id", help="Teable space for a new base (default: the space of the base your app has open)")
    args = parser.parse_args()

    real = Path(os.environ.get("APPDATA", "")) / "t3desk"
    home = Path(args.home)
    if home.resolve() == real.resolve():
        raise SystemExit("--home must not be the folder of your real work")
    home.mkdir(parents=True, exist_ok=True)

    source = server.App(real)  # read the connection settings of the real app; nothing is written there
    try:
        url, user, role = str(source.setting("teable_url", "") or ""), source.user, source.role
        current = str(source.setting("base_id", "") or "")
        space = args.space_id
        if not space and not args.base_id:
            if not current:
                raise SystemExit("your app has no base open and --space-id was not given")
            space = source.client()._request("GET", f"/api/base/{current}").get("spaceId")
            if not space:
                raise SystemExit("could not read the space of the current base: pass --space-id")
    finally:
        source.close()

    app = server.App(home)
    try:
        if app.store.count_drafts():
            raise SystemExit(f"{home} already has {app.store.count_drafts()} drafts: use an empty folder")
        app.store.set_setting("teable_url", url)
        post(app, "/api/settings", {"user": user, "role": role})
        body = {"base_id": args.base_id, "project_name": args.name} if args.base_id else {"project_name": args.name, "space_id": space}
        created = post(app, "/api/bootstrap", body)
        print(f"base {created['base_id']} with {len(created['table_ids'])} tables")

        records = build()
        for table, fields in records:
            post(app, "/api/draft", {"table": table, "op": "create", "fields": fields})
        print(f"{len(records)} drafts saved")

        gates = app.dispatch("GET", "/api/rows", {"table": "cai_dat"}, None)[1]["rows"]
        for row in gates:
            if row["key"] in server.GATE_KEYS:
                post(app, "/api/draft", {"table": "cai_dat", "op": "update", "key": row["key"], "record_id": row["record_id"],
                                         "base_modified": row["modified"], "base_fields": row["base"], "fields": {"gia_tri": "Có"}})

        result = post(app, "/api/commit", {})
        counts: dict[str, int] = {}
        for r in result["results"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        print("commit:", counts, "ok" if result["ok"] else "NOT OK")
        for r in result["results"]:
            if r["status"] != "committed":
                print("  ", r["table"], r["key"], r["status"], r.get("message", ""))
        app.dispatch("POST", "/api/refresh", {}, {})
        state = app.dispatch("GET", "/api/state", {}, None)[1]
        print("menu counts:", {k: v["n"] for k, v in state["menu_counts"].items()})
        print("drafts left:", state["drafts"])
    finally:
        app.close()


if __name__ == "__main__":
    main()
