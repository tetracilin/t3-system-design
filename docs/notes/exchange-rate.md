# Exchange rates

Decision (6 Oct 2026): rates are entered as VND per ONE unit of the currency, the way people say
them: 1 EUR = 27000 VND, 1 USD = 25000 VND. VND is always 1 and has no row.

- Keys in `cai_dat`: `vnd_per_usd`, `vnd_per_eur` (prefix `vnd_per_` + lower-case code; any other
  currency is added the same way). Defaults live in `schema.yaml` (`defaults.cai_dat`), config in
  `schema.yaml` `exchange_rates`. Labels: "1 EUR = ? VND" in `labels_vi.yaml` `settings_keys`.
- `rules.py` keeps every cost in million VND: `million_vnd = amount * rate_vnd / 1_000_000`
  (`to_million_vnd`). 1000 EUR = 27 million VND. Unknown currency gives no price.
- Old unit: earlier versions stored `ty_gia_VND/USD/EUR` as million VND per unit (0.000001, 0.025,
  0.027). Bootstrap never changes existing rows, so those rows exist in current bases. Reusing the
  keys would have read 0.027 as 0.027 VND, therefore new keys were chosen and rules never read
  `ty_gia_*`. Bootstrap adds the missing new rows, lists the old rows as OBSOLETE in its output,
  and deletes nothing (rule 1). Users may ignore the old rows.
- Validation (`validation.py`, texts in `labels_vi.yaml` `rate_messages`): the value must be a
  positive plain number; "27.000" and "27,000" are refused as ambiguous; a USD or EUR rate below 1
  is refused as the old unit (code `rate_old_unit`).
- The USD and EUR values are placeholders: confirm the real rates with Viet.
