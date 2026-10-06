# Foundation area notes: inferences and departures

Files: pyproject.toml, t3desk/{__init__,__main__,main,schema,teable_client,bootstrap}.py,
t3desk/data/{schema.yaml,labels_vi.yaml}, tests/{fake_teable,conftest,test_bootstrap,test_teable_client,test_schema}.py.

## Inferences (spec silent)
- doi_chieu extra fields: `ma_uv`, `ma_ts`, `danh_gia_tay` (Đạt / Không đạt / Không rõ), `gia_tri_so` (number, converted value),
  `trich_dan` (verbatim quote), `trang` (page), `ghi_chu`. Taken from sections 7 and 12 test 9 and the designer tree text.
- mua_hang.tinh_trang_nguon six-step scale (worst to best): Chưa hỏi, Không có hàng, Chỉ đặt theo đơn, Hàng về chậm, Có hàng một phần, Có hàng sẵn.
  mua_hang.trang_thai_mua: Mở / Đã báo giá / Đóng ("rejected but still open" rule needs an "open" state).
- moc.trang_thai: Kế hoạch / Đang làm / Xong / Hủy. sai_lech.trang_thai and cong_viec.trang_thai: Mở / Xong / Hủy.
- Choice sets for `uu_tien` (H, M, L), `loai_gia`, `nguoi_tim`, `loai` (RFQ, RFP) copied from the requirements.
- Reference fields (validated before commit): `yc_then_chot` (multi, `;`), `thay_the`, `ds_ma_uv`, `ds_ma_nut`, `phuong_an` is NOT a reference.
  `ma_yc_goc` also accepts the literal `Dẫn xuất` (`ref_extra`). `mua_hang.ma_uv` is both the ID and a reference to ung_vien.
- Money: `tien_te` is free text; `cai_dat` rate rows are `vnd_per_<cur>` holding VND per ONE unit (USD 25000, EUR 27000 placeholders; VND is built in as 1); old `ty_gia_<CUR>` rows are obsolete, see `exchange-rate.md`.
- Scoring weights keys: trong_so_ky_thuat 0.5, trong_so_nguon_hang 0.3, trong_so_thoi_gian 0.2 (placeholders). Gates default `Không`.
  `cai_dat.gia_tri` is single-line text for every key; consumers parse numbers.
- rfq IDs: `RFQ-001` and `RFP-001` each have their own counter (`prefixes` list in schema).
- ID kinds: number, letter (KT-A..Z, None after Z), tree (N0, N1, N1.1, max 3 levels; child needs `parent`), free (moc), reference (mua_hang),
  composite (doi_chieu `UV|TS`, cong_viec `CV|source|subject`), key (cai_dat). `next_free_id` proposes only number, letter and tree.
- Dates are Teable `date` fields (cap_nhat_luc, dong_bo_luc too); system fields are named auto_number, created_time, last_modified_time, created_by, last_modified_by.
- Ignored by bootstrap on purpose: differences in choice lists, number/date formatting (only type, unique, notNull are compared).
- Duplicate detection: `TeableError.is_unique_violation` = HTTP 4xx and (409, or message contains "unique"/"duplicate"). The real Teable error text is unverified.
- Retries: GET retried on 429/502/503/504 and network errors; writes retried only when the TCP connection was never made, so a create never runs twice.
- `find_by_field` resolves the field name to a field id first because Teable filters use `fieldId`.
- Extra module t3desk/schema.py (loader, labels, Teable payloads, next_free_id) is not in the section 12 layout; other areas should reuse it.
- Bootstrap CLI does not choose a default settings path (that belongs in platform.py); it prints the settings JSON unless `--settings-file` is given.
  Token comes from `--token`, env `T3DESK_TEABLE_TOKEN`, or a prompt; it is never written to the settings file.
- tests use `pythonpath = [".", "tests"]` (pyproject) so `from fake_teable import FakeTeable` and `import tests.fake_teable` both work.

## Departures
- Scratch table `zz_scratch_check` stays in the base (nothing may be deleted); one record is added per bootstrap run. It is not counted as one of the 14 tables,
  so a bootstrapped base holds 15 tables. Pass `scratch_check=False` to skip.
- Section 12 test 4 (commit refused) is covered here only at the client level (`ensure_unique_flags` raises `UniqueFlagError` naming `table.field`);
  the commit module must call it at start-up and before each commit.

## Unverified (no real Teable available)
- Every path and payload in teable_client.py against a deployed Teable: table create with `fields` and `records: []`, `unique`/`notNull` accepted inside
  table-create fields, number/date `options.formatting`, `GET /api/base/{id}/table`, `GET /api/auth/user`, `POST /api/base` with `spaceId`, filter shape,
  `createdBy` shape in records, whether a unique violation is HTTP 400 or 409.
- The fake server mirrors these assumptions, so passing tests do not prove them.
