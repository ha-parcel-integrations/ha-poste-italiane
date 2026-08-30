"""Tests for Poste Italiane payload normalisation."""
from datetime import datetime, timedelta, timezone

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poste_italiane.const import (
    CAPABILITIES,
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DOMAIN,
    KNOWN_CAPABILITIES,
    ParcelStatus,
)
from custom_components.poste_italiane.parcels import (
    apply_delivered_filter,
    build_history,
    map_event_status,
    map_parcel_status,
    normalize_parcel,
    parse_delivery_estimate,
    sort_parcels_by_ts,
    to_iso_timestamp,
)

from .payloads import active_sample, crono_sample, delivered_sample, movement


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("La spedizione è stata presa in carico da un nostro operatore", ParcelStatus.REGISTERED),
        ("da un nostro operatore presso l'Ufficio Postale", ParcelStatus.REGISTERED),
        ("la spedizione è in transito presso il Centro", ParcelStatus.IN_TRANSIT),
        ("completata la fase di verifica per lo svincolo presso il Centro", ParcelStatus.IN_TRANSIT),
        ("la spedizione è in consegna", ParcelStatus.OUT_FOR_DELIVERY),
        ("la spedizione è stata consegnata", ParcelStatus.DELIVERED),
        ("presso il paese estero in data", ParcelStatus.IN_TRANSIT),
        ("in data", ParcelStatus.IN_TRANSIT),
        ("con successo in data", ParcelStatus.DELIVERED),
        ("consegna non andata a buon fine. Contatta Assistenza", ParcelStatus.PROBLEM),
        ("Sono in corso delle verifiche sulla spedizione. Contatta Assistenza", ParcelStatus.PROBLEM),
        ("consegna non andata a buon fine perché l'indirizzo del destinatario risulta errato o incompleto. Contatta Assistenza", ParcelStatus.PROBLEM),
        ("in restituzione al mittente", ParcelStatus.RETURNING),
        ("disponibile per il ritiro dal giorno lavorativo successivo alla data indicata", ParcelStatus.AT_PICKUP_POINT),
        ("a seguito di acquisto da poste.it", ParcelStatus.REGISTERED),
    ],
)
def test_maps_confirmed_status_wording(text, expected):
    assert map_parcel_status(text) is expected


def test_unknown_status_warns_once_and_history_keeps_unknown(caplog):
    assert map_parcel_status("nuovo stato") is ParcelStatus.UNKNOWN
    assert map_event_status("nuovo stato") is ParcelStatus.UNKNOWN
    assert caplog.text.count("nuovo stato") == 1
    assert "issues/new" in caplog.text


def test_epoch_milliseconds_are_converted_to_utc():
    assert to_iso_timestamp(1767300000000) == "2026-01-01T20:40:00+00:00"


def test_parses_italian_delivery_estimate_as_a_local_day_window():
    assert parse_delivery_estimate("Consegna prevista entro Martedì 21 Gennaio 2025") == (
        "2025-01-21T00:00:00+01:00", "2025-01-21T23:59:59.999999+01:00"
    )


def test_history_is_oldest_first_and_capped():
    history = build_history(delivered_sample()["listaMovimenti"])
    assert [entry["status"] for entry in history] == [
        ParcelStatus.REGISTERED, ParcelStatus.IN_TRANSIT,
        ParcelStatus.OUT_FOR_DELIVERY, ParcelStatus.DELIVERED,
    ]
    events = [movement("la spedizione è in transito", 1767000000000 + day) for day in range(25)]
    assert len(build_history(events)) == 20


def test_normalize_publishes_exact_contract_and_full_raw_response():
    raw = delivered_sample()
    parcel = normalize_parcel(raw, include_history=True)
    assert list(parcel) == [
        "carrier", "barcode", "sender", "receiver", "status", "raw_status", "delivered",
        "delivered_at", "planned_from", "planned_to", "pickup", "pickup_point", "url",
        "weight", "dimensions", "history", "raw",
    ]
    assert parcel["carrier"] == "Poste Italiane"
    assert parcel["barcode"] == "CW000000000IT"
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] == "2026-01-01T20:40:00+00:00"
    assert parcel["sender"] is parcel["receiver"] is None
    assert parcel["planned_from"] is parcel["planned_to"] is None
    assert parcel["pickup"] is False and parcel["pickup_point"] is None
    assert parcel["weight"] is parcel["dimensions"] is None
    assert parcel["history"][-1]["status"] is ParcelStatus.DELIVERED
    assert parcel["raw"] is raw


def test_latest_recognised_event_drives_active_status_and_uses_tracking_url():
    parcel = normalize_parcel(active_sample())
    assert parcel["status"] is ParcelStatus.OUT_FOR_DELIVERY
    assert parcel["delivered"] is False
    assert parcel["planned_from"] == "2026-01-01T00:00:00+01:00"
    assert parcel["planned_to"] == "2026-01-01T23:59:59.999999+01:00"
    assert parcel["url"].endswith("LX000000000JP")


def test_status_code_five_overrides_an_unrecognised_latest_event():
    raw = crono_sample()
    raw["listaMovimenti"].append(movement("nuovo stato", 1767400000000))
    assert normalize_parcel(raw)["status"] is ParcelStatus.DELIVERED


def test_capabilities_are_accurate():
    assert CAPABILITIES == frozenset({"delivery_window", "url", "history"})
    assert CAPABILITIES <= KNOWN_CAPABILITIES


def test_sort_and_delivered_filter_keep_contract():
    ordered = sort_parcels_by_ts(
        [{"barcode": "a", "delivered_at": "2026-05-02T10:00:00Z"}, {"barcode": "b", "delivered_at": None}],
        "delivered_at", descending=True,
    )
    assert [parcel["barcode"] for parcel in ordered] == ["a", "b"]
    entry = MockConfigEntry(domain=DOMAIN, unique_id=DOMAIN, options={
        CONF_DELIVERED_FILTER_TYPE: "days", CONF_DELIVERED_FILTER_AMOUNT: 7,
    })
    now = datetime.now(timezone.utc)
    assert apply_delivered_filter([
        {"barcode": "recent", "delivered_at": (now - timedelta(days=1)).isoformat()},
        {"barcode": "old", "delivered_at": (now - timedelta(days=30)).isoformat()},
    ], entry)[0]["barcode"] == "recent"
