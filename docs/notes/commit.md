# Commit area notes: inferences and departures

Files: t3desk/{store,validation,commit}.py, tests/{test_store,test_commit}.py.

## Inferences (spec silent)
- doi_chieu key (`khoa`) is rebuilt as `<ma_uv>|<ma_ts>` when a rename rewrites its `ma_uv` / `ma_ts` (driven by schema `parts`/`separator`).
- Draft = row with op create/update, `key` (the record's ID), Teable record id, `base_modified` (lastModifiedTime) and `base_fields` for updates.
  An update draft holds only the changed fields; the ID field may not appear in it.
- A draft that depends on a draft that did not commit (conflict, invalid, failed) is SKIPPED, never sent, so a check cannot attach to someone else's
  record that happens to hold the same ID. After the user accepts a new ID the dependents are rewritten and go in the next commit (or the same one when `on_conflict` is passed).
- Conflict is resolved in two ways: `commit()` returns a `conflict` result with `taken_by`, `taken_at`, `proposed_id`, then `accept_new_id(draft_id, new_id)`;
  or `commit(on_conflict=callback)` where the callback returns the ID to use (or None to keep the draft).
- Next-free-ID proposal is taken from a fresh full listing of the table plus local drafts. Tree parent is derived from the ID text (`N1.2` -> `N1`), the rfq prefix from the old ID.
  Kinds without a proposal (free, composite, key, reference, or letter past Z) give `proposed_id=None`.
- Stale edit: `StaleInfo.fields` lists every drafted field with base/mine/theirs and `theirs_changed`. `resolve_stale(draft, {field: "mine"|"theirs"})`; unlisted fields default to "mine".
  "theirs" drops the field from the draft. The draft is rebased on the record as it is now. `on_stale` callback does the same inside a commit.
- A stale check is triggered by any lastModifiedTime difference, as the spec says, even when the other user touched different fields.
- Validation messages are English with a `code`; the UI maps codes to Vietnamese labels. Date fields must start `YYYY-MM-DD`; numbers must be JSON numbers.
- Validation is not an error for an ID that already exists in Teable (that is a commit-time conflict, not a form error).
- Offline: `can_commit()` pings Teable; any TeableError makes commit disabled and `commit()` raises `CommitDisabledError` before touching drafts. A connection lost mid-commit
  fails the current draft and marks the rest SKIPPED (kept as drafts).
- Secrets: `save_secret`/`load_secret` try the OS keyring (only if a real backend, not keyring's "fail" backend), else a `0600` file in the config folder. On Windows `chmod` has no effect;
  the file relies on the user's profile ACLs. `Store.set_setting` refuses keys containing token/secret/password.

## Departures
- Withdrawal on read-back duplicate: the spec says the app "withdraws its own record". Rule 1 forbids delete and an ID cannot be edited, so the app RETIRES its own record by
  setting the table's status field to `Hủy`/`Loại` (first available choice). Tables without such a status (doi_chieu, mua_hang, cai_dat, cong_viec, ...) cannot be retired;
  the result message says the duplicate needs a manual fix. It is only reachable if Teable's unique constraint fails, so it is a safety net. Never another user's record is touched.
- `RETIRE_VALUES = ("Hủy", "Loại")` is a Vietnamese data literal in commit.py (schema data value, not UI text).
- Tests were written together with the code rather than strictly test-first.
- Tests for acceptance test 8 run with a client that has `retries=0`; on Windows each refused connection takes about 4 s, so the default retries made the test slow.
- Test 4 is covered here at commit level too (`test_commit_refused_when_unique_flag_missing_names_the_field`).

## Unverified
- Real Teable's duplicate-ID error shape (relies on `TeableError.is_unique_violation`), `createdTime`/`autoNumber` on create responses, and `get_record` returning `lastModifiedTime`
  in the shape the fake uses.
- Read-back uses `find_by_field` (filter on field id); the fake supports it, a real Teable filter shape is unverified.
