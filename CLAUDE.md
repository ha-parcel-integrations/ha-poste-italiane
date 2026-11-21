# Working in this repository

Home Assistant custom integration for **Poste Italiane** parcel tracking.
Distributed via HACS; not part of HA core. One carrier in the
[ha-parcel-integrations](https://github.com/ha-parcel-integrations) suite,
**generated from ha-carrier-template** — everything outside *Carrier-specific
notes* is suite-wide; when in doubt check the template or a sibling repo.
No DTO layer.

## Shared conventions — fetch when relevant

Suite-wide rules live in
[`.github/CONVENTIONS.md`](https://github.com/ha-parcel-integrations/.github/blob/main/CONVENTIONS.md)
and are **not** repeated here. Don't fetch it every session — fetch it **before**
you act in one of these areas:

| Before you … | Fetch `CONVENTIONS.md` § |
|---|---|
| touch entities, sensors, config/options flow, coordinator, diagnostics, translations | *Home Assistant developer docs* (its table points on to the canonical HA page — don't rely on memory) |
| add/rename a parcel field, a `ParcelStatus`, or a bus event; change the sort/first-refresh; touch unmapped-status logging | *Parcel contract* — exact key set, units, sort, events + suppression; `test_parcels.py::test_normalize_publishes_exact_contract_and_full_raw_response` guards the key set |
| change which optional field this carrier populates vs. always returns `None` | Update `const.py`'s `CAPABILITIES` in the same commit — it feeds the comparison table on the docs site, so a field that starts (or stops) coming back non-null and isn't reflected there is a wrong claim on the website, not just a stale comment. If this carrier has more than one backend (a country-specific transport, not just a config option) with genuinely different field support, `CAPABILITIES` should be a `CAPABILITIES_BY_VARIANT` dict instead — one frozenset per backend, so a field only some backends populate doesn't get silently intersected away or overclaimed for the rest |
| ship anything while below 1.0.0 (unconfirmed data) | *Pre-1.0 releases* — one-shot WARNINGs for every guessed shape/code |
| consider "fixing" a lint/pattern the skill flags (poll interval, inline client, sync requests) | *Deliberate skill divergences* — likely intentional, don't re-flag |
| commit, bump, tag, release, or write release notes; add a feature without a test | *Workflow / Commits / Versioning / Testing* |

**Structure, options flow, dynamic polling and module layout are suite-wide**
and identical in every carrier — the authoritative spec is
[`ha-carrier-template/scaffold/CLAUDE.md`](https://github.com/ha-parcel-integrations/ha-carrier-template/blob/main/scaffold/CLAUDE.md).
This repo follows it exactly.

**Suite-wide tripwires, kept inline on purpose:**
- **First refresh in `__init__.py`, before `async_forward_entry_setups`** — from
  a forwarded platform HA can't catch `ConfigEntryNotReady` and half-sets-up the
  entry. Runtime-only; tests don't catch a regression.
- **Setup stale-entity sweep is scoped to `domain == "sensor"` and skips
  `non_parcel_unique_ids`** — else it deletes the refresh button / the
  summary+diagnostic sensors. Add a new non-parcel sensor's unique_id to the set.
- **Per-parcel sensors are removed by the summary sensor** via
  `entity_registry.async_remove` (self-removal races and leaves ghosts).

## Carrier-specific notes

This is an account-less, public tracking-code integration. It polls one code
per request and retains the last successful parcel when the carrier briefly
answers that a previously known code cannot be found. Its public response has no
size, weight, sender or receiver fields, so those canonical fields are
intentionally `None`. **`pickup` is `True`** once the parcel has reached `at_pickup_point` in any
event Poste returned, so it stays `True` after collection (Poste gives no
structured destination field). **`pickup_point` is the point's name only**, never
its street address, and only when `pickup` is `True`: from `denominazioneUfficio`
or an `Ufficio Postale` that names itself in `luogo` (Poste sends no separate
name there, so that label is published as sent) — but **only on an event whose
own wording says the parcel is collectable**. Poste fills those same office
fields on its own sorting centres, so reading them unconditionally named a depot
as the pickup point on ordinary doorstep deliveries; and `luogo` on a delivery
event is the recipient's own address, so it is never read blind. A handover at a
Punto Poste by the sender is not a pickup route. The Italian
`dataPrevistaConsegna` text is a date with no time, so the window is that local
day, `00:00:00` to `23:59:59` (Europe/Rome), emptied at `at_pickup_point`,
`returning` and `delivered`; `url`, that window and opt-in `history` are
capabilities.

**Pickup sensors:** both `awaiting_pickup` and `en_route_to_pickup_point` exist.
`en_route_to_pickup_point` stays at 0 in practice: with no structured
destination field, `pickup` only turns `True` when the parcel reaches
`at_pickup_point`, so a parcel is never "on its way" to a point beforehand.
Pending evidence: a route flag or wording that announces a pickup-point
destination before arrival.

**`delivered` is `status is DELIVERED` only.** `stato == "5"` is folded into the
status mapping and wins over `at_pickup_point` (collected is delivered). On a
`returning` parcel it does not count: the contract wants evidence of delivery at
the sender, and that wording has not been seen, so it stays `returning` with
`delivered` False.

**Open / unverified:** `_PICKUP_EVENT_PREFIXES` includes `presa in carico presso
il Punto Poste`, which might be a sender drop-off rather than a collection
point. Left as is until a real parcel shows which it is.

A 2026-10-17 sweep of fourteen real parcels confirmed the return
(`in restituzione al mittente`), collection (`disponibile per il ritiro`) and
failed-attempt (`consegna non andata a buon fine`) families, and the
`Punto Poste` / `Punto Poste-Locker` handover wording. Two traps it exposed:

- **Poste writes `è` as the ASCII `e'` on some responses** — the very same
  sentence arrived both ways across parcels, so `map_parcel_status` folds
  `e'` back to `è` before matching. Without it a delivered parcel fell to
  `unknown` purely on typography.
- **Collection has more than one wording** (`…dal giorno lavorativo
  successivo…` and `…entro i termini indicati su sms/email`), so the match is
  on the `disponibile per il ritiro` prefix rather than either full sentence.

The confirmed status vocabulary is still incomplete. Unknown status text must
remain `unknown` and emit the suite one-shot warning; do not infer return,
collection or failure semantics beyond the families above. 

## Running tests

```
python -m pytest tests/ --cov=custom_components.poste_italiane
```

Coverage must stay **above 95%** (silver `test-coverage` rule). Run before
committing. A code change updates the README + this file + `docs/` in the same
commit.
