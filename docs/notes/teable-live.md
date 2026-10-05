# Teable live verification (5 Oct 2026)

Server: `https://teable.tecotec.tech:8443`, **release.2026-08-19T02-25-59Z.2698** (git 904cbef, edition EE,
PostgreSQL, MinIO storage). The version is read from `window.__TE__.buildVersion` in the web page
(`GET /`); there is no JSON version endpoint (`/api/version` is 404).

All probing happened in the throwaway base **`t3desk-scratch-20261005-1742`** (id `bseckzlFbGVvwCcydow`)
in space T3 (`spckXJPPbWImvdsqIdu`). Nothing else in the space was listed or changed. Nothing was deleted.
The base was left in place; it holds the 14 schema tables, `zz_scratch_check`, and four probe tables
(`probe1` x2, `probe_norec`, `probe_date`) made by hand while testing.

## VERIFIED against the real server

- Connection test: `GET /api/space` works with the token (200, list of `{id,name,avatar,role}`). A bad or missing token
  is **401** `{"message":"Unauthorized","status":401,"code":"unauthorized"}` on every route (the "200 anonymous"
  answer was not seen). `GET /api/auth/user` returns 200 `{id,email,avatar,name}` for this token;
  `/api/auth/user/me` is 403 (`restricted_resource`). Client `ping()` now calls `/api/space`, then
  `/api/auth/user` (403/404 tolerated), and refuses an identity that looks anonymous.
- `POST /api/base` `{spaceId, name}` -> 201 `{id,name,icon,spaceId}`.
- `GET /api/base/{id}/table` -> 200 plain list of tables (no fields).
- `POST /api/base/{id}/table` `{name, fields, records: []}` -> 201 with `id`, `fields[]`, `views[]`. `unique` and
  `notNull` inside table-create fields are honoured and echoed (`notNull` key is absent when not set). The first field
  is the primary field. **Leaving out `records` makes Teable add 3 blank rows**, so `records: []` is needed.
- Field options accepted as sent: `singleSelect` choices (ids and colours are added), `number.formatting
  {type: decimal, precision: 4}`, `date.formatting {date, time, timeZone}`. System types `autoNumber`, `createdTime`,
  `lastModifiedTime`, `createdBy`, `lastModifiedBy` are created from `{name, type}` only.
- `GET /api/table/{t}/field` -> plain list with `unique` / `notNull` / `type` (what `missing_unique_flags` reads).
- `POST /api/table/{t}/field` with `unique: true` works. With `notNull: true` on a table that already has rows it is
  **400** `validation.field.required_existing_values`.
- Record create `{fieldKeyType:"name", typecast, records:[{fields}]}` -> 201 `{records:[{id, fields}]}`.
  **The answer has no `autoNumber`, `createdTime`, `lastModifiedTime` and no system fields** (the old assumption was wrong).
- `GET /api/table/{t}/record/{r}` and list: top level has `id, fields, name, autoNumber, createdTime,
  lastModifiedTime, createdBy, lastModifiedBy` (the last two are user ids); `fields` also holds the system fields by
  their names. `created_by` / `last_modified_by` inside `fields` are objects `{id, email, title, avatarUrl}`;
  `record_author` (uses `title`) is right. Times are ISO UTC with milliseconds.
- `PATCH /api/table/{t}/record/{r}` `{fieldKeyType, typecast, record:{fields}}` -> 200 `{id, fields}` (whole record in
  `fields`, **no top-level `lastModifiedTime`**). `null` clears a field. The commit code now re-reads the record after a
  PATCH so the cache gets the new `lastModifiedTime`.
- Unique violation: **HTTP 400**, `code: "validation_error"`, `data.domainCode: "validation.field.unique"`, message
  `Cannot complete insert: field fld... must have a unique value` (`... update: ...` on PATCH). Same with typecast on.
  `is_unique_violation` now keys on the domain code, with the old text check as fallback when no code is present.
- Other errors: not-null 400 `validation.field.not_null` ("violates not-null constraint" when the field is missing,
  "cannot be empty" when empty); bad choice 400 `validation.field.invalid_value` ("expected one of ..."); bad number
  400; **unknown field name 404** `field.key_not_found`; a value for a computed field is silently ignored (201).
  With `typecast: true` an unknown choice value is accepted and stored, so commit keeps `typecast=False`.
- Filter: `filter` as a JSON string `{"conjunction":"and","filterSet":[{"fieldId":..,"operator":"is","value":..}]}`
  works; `fieldId` accepts the field id **and** the field name. `is` on text is case-sensitive and exact (`r1` does not
  find `R1`; `R` does not find `R1`). Unicode and quote characters in unique values are fine.
- Paging: `take` 1..1000, `skip` offset; `take=1001` -> 400 "Can't take more than 1000 records", `take=0` -> 400
  "should at least take 1 record". Default order is creation order. `projection` and `fieldKeyType=id` work.
- Dates: a `date` field with `timeZone: "Asia/Ho_Chi_Minh"` turns "2026-10-05" into `2026-10-04T17:00:00.000Z`.
  The schema now uses `timeZone: "UTC"`, so "2026-10-05" comes back as `2026-10-05T00:00:00.000Z`, and the client
  turns that back into `2026-10-05` for date fields (looked up once per table). Date fields of older bases in another
  time zone are returned unchanged (UTC timestamp).
- Teable does **not** refuse a duplicate field name (creates `name 2`, 201) or a duplicate table name (201, second table
  with the same name). Bootstrap checks names before creating, so it is safe; do not create tables by hand in the base.
- `python -m t3desk bootstrap` equivalent (`run_bootstrap`) against the scratch base: run 1 created 14 tables, 12 `cai_dat`
  rows, scratch table, duplicate-ID check "refused as required"; run 2: no tables, fields or settings created, no
  mismatches. The duplicate check now accepts only a real unique violation as "refused" (a 404 or not-null 400 no longer passes).
- Commit flow with the real server (acceptance tests 2 and 3 style, one token acting as users A and B):
  A commits UV-207; B's draft with the same ID gets `conflict` ("already taken by vietanh (time) ... Next free ID: UV-208");
  the record in Teable is unchanged (same `lastModifiedTime`); B's thong_so committed; its dependent doi_chieu was
  skipped; after `accept_new_id` the recommit sent UV-208 and `doi_chieu UV-208|TS-201` (reference rewritten).
  Stale edit: a change made after the draft base gives `stale`; resolving with "mine" commits, other user's field kept.
  Date round trip through commit: "2026-10-05" in, "2026-10-05" out.
- `ensure_unique_flags` passes on the bootstrapped base (reads real `unique` flags).

## Still unverified

- Real conflict between two different users (only one token was available); `createdBy` of another user.
- Paging beyond one page (more than 1000 rows); only `take`/`skip` with tiny tables were probed.
- Removing a `unique` flag on the server and seeing commit refuse (flag read is verified, the removal was not done live).
- Rate limits, behaviour under many parallel commits, retry statuses (429/502/503/504) from the real server.
- A token limited to one base with only record permissions (the token used is an owner token of the space; bootstrap
  with a limited token will need table and field permissions).
- Date fields with a non-UTC time zone (old bases) are not normalised.
- The Docker image tags and environment variables in `deploy/` (the server is not run from this repository's compose file).
