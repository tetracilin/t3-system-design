"""Pressure-tank fixture (inferred from section 7 and acceptance test 9).

Tree: N0 root, five level-1 nodes N1..N5, four leaves under two of them
(N1.1 hydrophone, N1.2 digitiser, N2.1, N2.2). N3, N4 and N5 are leaves themselves.

Expected results at TODAY:
    N1.1 hydrophone   Xong
    N1.2 digitiser    step 3, "có 2, cần 3"
    N2.1, N2.2, N3, N4, N5   step 2 with 2, 1, 1, 1, 1 allocated requirements
    pairs missing a specification: 1 (R6 on N1.2)
    rows with any warning: 1 (PB-004, the R6 pair that has no specification)
"""

from __future__ import annotations

import copy
from datetime import date
from typing import Any

TODAY = date(2026, 10, 5)
Tables = dict[str, list[dict[str, Any]]]


def _node(code: str, parent: str | None, name: str, kind: str, owner: str | None, qty: float = 1) -> dict[str, Any]:
    return {"ma_nut": code, "ma_cha": parent, "ten": name, "loai": kind, "so_luong": qty, "phu_trach": owner}


def _alloc(n: int, yc: str, node: str, kind: str = "Mỗi nút phải đạt", **extra: Any) -> dict[str, Any]:
    return {"ma_pb": f"PB-{n:03d}", "ma_yc": yc, "ma_nut": node, "kieu": kind, **extra}


def _spec(n: int, node: str, yc: str, name: str, lo: float, hi: float | None, must: bool = True) -> dict[str, Any]:
    return {
        "ma_ts": f"TS-{n:03d}", "ma_nut": node, "ma_yc_goc": yc, "thong_so": name, "kieu": "Số",
        "gia_tri_min": lo, "gia_tri_max": hi, "don_vi": "u", "muc": "Bắt buộc" if must else "Mong muốn",
    }


def _cand(n: int, node: str, status: str = "Ứng viên", **extra: Any) -> dict[str, Any]:
    row = {
        "ma_uv": f"UV-{n:03d}", "ma_nut": node, "hang": "Hãng", "model": f"M{n}", "gia_cong_bo": 1000.0,
        "tien_te": "USD", "link_datasheet": f"http://ds.invalid/{n}", "ngay_kiem_tra": "2026-10-01",
        "nguoi_tim": "Người", "trang_thai": status,
    }
    if status in ("Chọn", "Loại"):
        row["ly_do"] = "Lý do"
    row.update(extra)
    return row


def _check(uv: str, ts: str, value: float, hand: str | None = None) -> dict[str, Any]:
    row = {"khoa": f"{uv}|{ts}", "ma_uv": uv, "ma_ts": ts, "gia_tri_so": value, "trich_dan": "nguyên văn", "trang": "3"}
    if hand:
        row["danh_gia_tay"] = hand
    return row


def build() -> Tables:
    """Return a fresh copy of the fixture tables."""
    t: Tables = {
        "cai_dat": [
            {"khoa": "ten_du_an", "gia_tri": "Bể áp lực"}, {"khoa": "so_uv_toi_thieu", "gia_tri": "3"},
            {"khoa": "so_uv_toi_da", "gia_tri": "5"}, {"khoa": "chot_cap_1", "gia_tri": "Có"},
            {"khoa": "chot_cap_2", "gia_tri": "Có"}, {"khoa": "ty_gia_VND", "gia_tri": "0.000001"},
            {"khoa": "ty_gia_USD", "gia_tri": "0.025"}, {"khoa": "ty_gia_EUR", "gia_tri": "0.027"},
        ],
        "yeu_cau": [
            {"ma_yc": "R1", "mo_ta": "Độ nhạy", "muc": "Bắt buộc", "trang_thai": "Đã chốt"},
            {"ma_yc": "R2", "mo_ta": "Dải tần", "muc": "Bắt buộc", "trang_thai": "Đã chốt"},
            {"ma_yc": "R3", "mo_ta": "Áp suất làm việc", "muc": "Bắt buộc", "trang_thai": "Đã chốt"},
            {"ma_yc": "R4", "mo_ta": "Khối lượng", "muc": "Bắt buộc", "trang_thai": "Đã chốt"},
            {"ma_yc": "R5", "mo_ta": "Thẩm mỹ", "muc": "Mong muốn", "trang_thai": "Đã chốt"},
            {"ma_yc": "R6", "mo_ta": "Nhiễu", "muc": "Bắt buộc", "trang_thai": "Đã chốt"},
        ],
        "kien_truc": [
            {"ma_kt": "KT-A", "ten": "Một bể", "trang_thai": "Chọn", "ly_do": "Đơn giản"},
            {"ma_kt": "KT-B", "ten": "Hai bể", "trang_thai": "Loại", "ly_do": "Đắt"},
        ],
        "nut": [
            _node("N0", None, "Hệ thống bể áp lực", "Hệ thống", None),
            _node("N1", "N0", "Cụm cảm biến", "Cụm", None),
            _node("N1.1", "N1", "Hydrophone", "Mua OEM", "an", 2),
            _node("N1.2", "N1", "Bộ số hóa", "Mua OEM", "binh"),
            _node("N2", "N0", "Cụm cơ khí", "Cụm", None),
            _node("N2.1", "N2", "Vỏ bể", "Tự chế tạo", "chi"),
            _node("N2.2", "N2", "Giá đỡ", "Tự chế tạo", "dung"),
            _node("N3", "N0", "Phần mềm", "Phần mềm", "em"),
            _node("N4", "N0", "Nguồn", "Mua OEM", "gia"),
            _node("N5", "N0", "Hiệu chuẩn", "Dịch vụ", "hoa"),
        ],
        "phan_bo": [
            _alloc(1, "R1", "N1.1"), _alloc(2, "R2", "N1.1"),
            _alloc(3, "R2", "N1.2"), _alloc(4, "R6", "N1.2"),
            _alloc(5, "R3", "N2.1"),
            _alloc(6, "R4", "N2.1", "Chia ngân sách", gia_tri_phan_bo=40.0, gioi_han_he_thong=100.0, cach_cong="Cộng"),
            _alloc(7, "R4", "N2.2", "Chia ngân sách", gia_tri_phan_bo=50.0, gioi_han_he_thong=100.0, cach_cong="Cộng"),
            _alloc(8, "R3", "N3"), _alloc(9, "R5", "N4"), _alloc(10, "R3", "N5"),
            _alloc(11, "R5", "N0", "Kiểm ở cấp hệ thống", cach_kiem_he_thong="Nghiệm thu"),
        ],
        "thong_so": [
            _spec(1, "N1.1", "R1", "Độ nhạy", -180, None),
            _spec(2, "N1.1", "R2", "Dải tần", 10, 20000),
            _spec(3, "N1.2", "R2", "Tần số lấy mẫu", 48, None),
        ],
        "ung_vien": [
            _cand(1, "N1.1", "Chọn"),
            _cand(2, "N1.1"),
            _cand(3, "N1.1", "Loại", gia_cong_bo=500.0),
            _cand(4, "N1.2"),
            _cand(5, "N1.2"),
        ],
        "doi_chieu": [
            _check("UV-001", "TS-001", -170), _check("UV-001", "TS-002", 100),
            _check("UV-002", "TS-001", -175), _check("UV-002", "TS-002", 50),
            _check("UV-003", "TS-001", -200), _check("UV-003", "TS-002", 50),
            _check("UV-004", "TS-003", 96), _check("UV-005", "TS-003", 96),
        ],
        "mua_hang": [
            {"ma_uv": "UV-001", "nha_cung_cap": "Hãng", "don_gia_bao": 1200.0, "tien_te": "USD",
             "tinh_trang_nguon": "Có hàng sẵn", "tg_cho_tuan": 4, "trang_thai_mua": "Đã báo giá",
             "bao_gia_het_han": "2027-01-01"},
            {"ma_uv": "UV-003", "tinh_trang_nguon": "Có hàng sẵn", "tg_cho_tuan": 2, "trang_thai_mua": "Đóng"},
        ],
        "moc": [{"ma_moc": "G4a", "ten": "Đặt hàng", "ngay_co_so": "2027-03-01", "ngay_du_bao": "2027-03-01"}],
        "quyet_dinh": [],
        "sai_lech": [],
        "rfq": [],
        "cong_viec": [],
    }
    return copy.deepcopy(t)
