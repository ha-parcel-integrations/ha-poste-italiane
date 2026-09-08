# Poste Italiane Parcel Tracker

[![Release](https://img.shields.io/github/v/release/ha-parcel-integrations/ha-poste-italiane.svg)](https://github.com/ha-parcel-integrations/ha-poste-italiane/releases)
[![Downloads](https://img.shields.io/github/downloads/ha-parcel-integrations/ha-poste-italiane/total.svg)](https://github.com/ha-parcel-integrations/ha-poste-italiane/releases)
[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> 💬 Questions or feedback? Join the discussion on the [Home Assistant community](https://community.home-assistant.io/t/packages-postnl-dhl-nl-dpd-and-gls-parcel-integration/112433/).

A custom Home Assistant integration that tracks [Poste Italiane](https://www.poste.it/) packages and parcels. No account is needed: enter the public tracking code, just as you would on the carrier's website.

Part of the [ha-parcel-integrations](https://github.com/ha-parcel-integrations) family: it publishes the same canonical parcel format, statuses and events as the other carrier integrations, so it plugs straight into the [Parcel Aggregator](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) and cross-carrier automations.

## Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Options](#options)
- [Removal](#removal)
- [Sensors](#sensors)
- [Parcel status reference](#parcel-status-reference)
- [Events](#events)
- [Services](#services)
- [Examples](#examples)
- [Debugging](#debugging)
- [Troubleshooting](#troubleshooting)
- [Related integrations](#related-integrations)
- [Disclaimer](#disclaimer)
- [Contributing](#contributing)
- [License](#license)

## Features

- Track any number of Poste Italiane parcels by tracking code — no account needed
- Per-parcel sensor with the canonical status, carrier status text, ETA and a tracking deep-link
- Summary sensors: incoming parcels, parcels awaiting pickup, next delivery and recently delivered parcels
- `poste_italiane.track_parcel` / `poste_italiane.untrack_parcel` services, so a dashboard button can add a parcel
- Events + device triggers for no-code automations (parcel registered, status changed, delivered, delivery time changed)
- Read-only **Deliveries** calendar with the expected delivery windows
- Opt-in per-parcel status history
- Manual refresh button and a diagnostic last-update sensor

## Requirements

- A Poste Italiane parcel and its tracking code (from the shipping
  confirmation email or the missed-delivery card) — no account needed

## Installation

### HACS (recommended)

1. In HACS, choose the three-dot menu → **Custom repositories**.
2. Add `https://github.com/ha-parcel-integrations/ha-poste-italiane` as an **Integration**.
3. Install **Poste Italiane** and restart Home Assistant.

### Manual

Copy `custom_components/poste_italiane` into your `config/custom_components/` folder and restart Home Assistant.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration → Poste Italiane**. There is nothing to fill in: the hub is created immediately (Poste Italiane tracking needs no account).

Then add parcels via the integration's **Configure** dialog, the [`poste_italiane.track_parcel`](#services) service, or a [dashboard button](examples/dashboards/add_parcel_card.yaml). The tracking code is on your shipping confirmation email or the missed-delivery card.

## Options

Open **Configure** on the integration entry:

| Section | Option | Default | Description |
|---|---|---|---|
| Parcels | Add / remove | — | Manage the tracked tracking codes. Changes apply immediately, no restart. |
| Delivered parcels | Filter by / amount | last 7 days | How long delivered parcels stay visible on the delivered sensor. |
| Parcel history | Include status history | off | Adds a `history` attribute per parcel with each status update. |

Polling isn't one of these settings: the integration polls on a dynamic,
status-driven schedule (quiet overnight window, faster when a parcel is out
for delivery, stopped entirely once nothing is left to track) with nothing to
configure. See [CLAUDE.md](CLAUDE.md) for the details.

## Removal

Standard HA removal applies: **Settings → Devices & Services → Poste Italiane → ⋮ → Delete**. Nothing is stored on Poste Italiane's side.

## Sensors

| Entity | Description |
|---|---|
| `sensor.poste_italiane_incoming_parcels` | Number of active tracked parcels, full list under the `parcels` attribute |
| `sensor.poste_italiane_parcel_<code>` | One per tracked parcel; state is the canonical status, attributes carry the full normalised parcel |
| `sensor.poste_italiane_awaiting_pickup` | Number of parcels waiting for collection at a Poste Italiane pickup point (`at_pickup_point`), full list under the `parcels` attribute |
| `sensor.poste_italiane_next_delivery` | Earliest expected delivery moment across all active parcels |
| `sensor.poste_italiane_delivered_parcels` | Recently delivered parcels (see the retention option) |
| `sensor.poste_italiane_last_successful_update` | Diagnostic: when Poste Italiane was last polled successfully |

A delivered parcel moves from its per-parcel sensor to the delivered sensor automatically.

## Parcel status reference

The `status` field is the carrier-agnostic enum shared by the whole integration family:

| Status | Meaning |
|---|---|
| `registered` | Announced / received by Poste Italiane |
| `in_transit` | In the sorting network |
| `out_for_delivery` | With the courier today |
| `at_pickup_point` | Waiting for collection at a pickup point |
| `delivered` | Delivered |
| `returning` | On the way back to the sender |
| `problem` | Poste Italiane reports an exception and refers you to support |
| `unknown` | Not yet scanned, or a status we have not mapped yet |

The carrier's own human-readable text is always available as `raw_status`.

## Events

The integration fires these on the event bus (also available as device triggers on the Poste Italiane device):

| Event | When |
|---|---|
| `poste_italiane_parcel_registered` | A new parcel appears in the active list |
| `poste_italiane_parcel_status_changed` | A parcel's canonical status changes (`old_status` / `new_status` in the payload), except the final hop to delivered |
| `poste_italiane_parcel_delivered` | A parcel is delivered |
| `poste_italiane_parcel_delivery_time_changed` | The expected delivery window changes |

Every payload is the full normalised parcel plus the hub's `device_id`. Events are suppressed on the first refresh after start-up.

## Services

| Service | Fields | Description |
|---|---|---|
| `poste_italiane.track_parcel` | `tracking_code` | Start tracking a parcel |
| `poste_italiane.untrack_parcel` | `tracking_code` | Stop tracking a parcel |

## Examples

Ready-to-paste automations and dashboard snippets live in [`examples/`](examples/), including tracking a new parcel straight from a dashboard.

### Community Lovelace cards

Third-party cards that work with this integration's sensors:

- [jonisnet/hki-parcels-card](https://github.com/jonisnet/hki-parcels-card)
- [klaptafel/ha-package-tracker-card](https://github.com/klaptafel/ha-package-tracker-card)

## Debugging

```yaml
logger:
  logs:
    custom_components.poste_italiane: debug
```

## Troubleshooting

- **A parcel shows `unknown`** — the code may not be known yet, or Poste Italiane reported a status that this pre-1.0 integration has not mapped. A previously known parcel is retained during an intermittent empty response.
- **A status logs "Unrecognised Poste Italiane status"** — please [open an issue](https://github.com/ha-parcel-integrations/ha-poste-italiane/issues/new) with the logged line so the mapping can be extended.

## Related integrations

This integration is part of [**ha-parcel-integrations**](https://github.com/ha-parcel-integrations) — a family of
parcel-carrier integrations that all publish the same canonical parcel format,
statuses and events.

- [**Parcel Aggregator**](https://github.com/ha-parcel-integrations/ha-parcel-aggregator) rolls every installed carrier
  up into one set of sensors.
- Browse [the organisation](https://github.com/ha-parcel-integrations) for the current list of supported carriers.

## Disclaimer

This integration uses the same public tracking endpoint as the Poste Italiane consumer website. It is not affiliated with, endorsed by, or supported by Poste Italiane.

## Contributing

Pull requests and issues are welcome. Please open an issue before
submitting a large change.

## License

[MIT](LICENSE)
