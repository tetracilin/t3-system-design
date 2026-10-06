"""schema.yaml and labels_vi.yaml are consistent and drive ID proposals."""

from __future__ import annotations

import re

import pytest

from t3desk import rules
from t3desk import schema as s

EXPECTED_TABLES = [
    "yeu_cau", "kien_truc", "nut", "phan_bo", "thong_so", "ung_vien", "doi_chieu",
    "mua_hang", "moc", "quyet_dinh", "sai_lech", "cai_dat", "rfq", "cong_viec",
]


def test_fourteen_tables_in_order(schema):
    assert s.table_keys(schema) == EXPECTED_TABLES


def test_every_table_has_an_id_field_first_unique_and_not_null(schema):
    for table, spec in schema["tables"].items():
        fields = spec["fields"]
        assert next(iter(fields)) == spec["id_field"], table
        assert fields[spec["id_field"]]["unique"] is True and fields[spec["id_field"]]["notNull"] is True
        assert fields[spec["id_field"]]["type"] == "text"
        others = [n for n, f in fields.items() if n != spec["id_field"] and f.get("unique")]
        assert others == [], table


def test_id_examples_match_their_own_patterns(schema):
    for table, spec in schema["tables"].items():
        assert re.fullmatch(spec["id"]["pattern"], spec["id"]["example"]), table


def test_references_point_to_real_tables_and_choice_fields_have_choices(schema):
    for table, spec in schema["tables"].items():
        for name, field in spec["fields"].items():
            if "ref" in field:
                assert field["ref"] in schema["tables"], (table, name)
            if field["type"] == "choice":
                assert field["choices"] and len(set(field["choices"])) == len(field["choices"]), (table, name)
            if "default" in field:
                assert field["default"] in field["choices"], (table, name)
            assert field["type"] in s.TEABLE_TYPES, (table, name)


def test_choice_values_from_requirements(schema):
    f = lambda t, n: schema["tables"][t]["fields"][n]["choices"]  # noqa: E731
    assert f("yeu_cau", "muc") == ["Bắt buộc", "Mong muốn"]
    assert f("nut", "loai") == ["Hệ thống", "Cụm", "Mua OEM", "Tự chế tạo", "Phần mềm", "Dịch vụ"]
    assert f("phan_bo", "kieu")[3] == "Kiểm ở cấp hệ thống"
    assert f("rfq", "trang_thai") == ["Nháp", "Đang tạo", "Đã tạo", "Đã gửi", "Đã có trả lời", "Hủy"]
    assert len(f("mua_hang", "tinh_trang_nguon")) == 6
    assert f("cong_viec", "nguon") == ["buoc", "cho_nhan", "sai_lech", "rfq", "canh_bao"]


def test_scores_are_one_to_five(schema):
    for name in ("diem_ky_thuat", "diem_nguon_hang", "diem_thoi_gian"):
        f = schema["tables"]["kien_truc"]["fields"][name]
        assert (f["min"], f["max"]) == (1, 5)


def test_labels_cover_every_table_field_and_setting(schema):
    labels = s.load_labels()
    for table, spec in schema["tables"].items():
        assert labels["tables"][table], table
        for name in spec["fields"]:
            assert s.field_label(labels, table, name) != name, (table, name)
    for system in schema["system_fields"]:
        assert system["name"] in labels["system_fields"]
    for row in schema["defaults"]["cai_dat"]:
        assert row["khoa"] in labels["settings_keys"]


def test_default_settings_cover_required_keys(schema):
    keys = {r["khoa"] for r in schema["defaults"]["cai_dat"]}
    assert {"ten_du_an", "ngan_sach_tr", "so_uv_toi_thieu", "so_uv_toi_da", "chot_cap_1", "chot_cap_2"} <= keys
    assert len([k for k in keys if k.startswith("trong_so_")]) == 3
    assert {"vnd_per_usd", "vnd_per_eur"} <= keys
    assert not any(k.startswith("ty_gia_") for k in keys)
    cfg = schema["exchange_rates"]
    assert all(k.startswith(cfg["key_prefix"]) for k in keys if "_per_" in k)
    assert rules.RATE_KEY_PREFIX == cfg["key_prefix"]


def test_teable_payload_for_each_type(schema):
    choice = s.teable_field_payload("muc", schema["tables"]["yeu_cau"]["fields"]["muc"])
    assert choice["type"] == "singleSelect"
    assert choice["options"]["choices"][0] == {"name": "Bắt buộc"}
    idf = s.teable_field_payload("ma_yc", schema["tables"]["yeu_cau"]["fields"]["ma_yc"])
    assert idf == {"name": "ma_yc", "type": "singleLineText", "unique": True, "notNull": True}
    assert s.teable_field_payload("n", {"type": "number"})["type"] == "number"
    assert s.teable_field_payload("d", {"type": "date"})["type"] == "date"
    assert s.teable_field_payload("t", {"type": "longtext"})["type"] == "longText"


@pytest.mark.parametrize(
    "table,existing,kwargs,expected",
    [
        ("yeu_cau", [], {}, "R1"),
        ("yeu_cau", ["R1", "R12", "R3"], {}, "R13"),
        ("ung_vien", ["UV-006", "UV-007"], {}, "UV-008"),
        ("ung_vien", ["UV-999"], {}, "UV-1000"),
        ("phan_bo", [], {}, "PB-001"),
        ("kien_truc", [], {}, "KT-A"),
        ("kien_truc", ["KT-A", "KT-C"], {}, "KT-D"),
        ("kien_truc", ["KT-Z"], {}, None),
        ("quyet_dinh", ["D2"], {}, "D3"),
        ("rfq", ["RFQ-001", "RFP-004"], {}, "RFQ-002"),
        ("rfq", ["RFQ-001", "RFP-004"], {"prefix": "RFP-"}, "RFP-005"),
        ("nut", ["N0", "N1", "N2", "N1.1"], {}, "N3"),
        ("nut", ["N0", "N1", "N1.1", "N1.2"], {"parent": "N1"}, "N1.3"),
        ("nut", ["N1", "N1.1.1"], {"parent": "N1.1"}, "N1.1.2"),
        ("nut", ["N1"], {"parent": "N2"}, "N2.1"),
        ("moc", [], {}, None),
        ("doi_chieu", [], {}, None),
        ("cai_dat", [], {}, None),
    ],
)
def test_next_free_id(schema, table, existing, kwargs, expected):
    assert s.next_free_id(schema, table, existing, **kwargs) == expected


def test_next_free_id_rejects_unknown_prefix(schema):
    with pytest.raises(ValueError):
        s.next_free_id(schema, "rfq", [], prefix="XYZ-")


def test_next_free_id_ignores_foreign_ids(schema):
    assert s.next_free_id(schema, "yeu_cau", ["UV-009", "", "Rx"]) == "R1"
