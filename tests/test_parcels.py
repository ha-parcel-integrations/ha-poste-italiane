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
    format_dimensions,
    map_event_status,
    map_parcel_status,
    normalize_parcel,
    parse_delivery_estimate,
    pickup_point,
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
        ("consegna non andata a buon fine. La spedizione tornerà in consegna a partire dal primo giorno lavorativo utile. Contatta Assistenza", ParcelStatus.PROBLEM),
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
    assert CAPABILITIES == frozenset(
        {"delivery_window", "pickup_point", "url", "history"}
    )
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


def test_ascii_apostrophe_variant_of_e_accent_still_maps(caplog):
    """Poste sends the same sentence as both "è" and "e'"."""
    assert map_parcel_status("La spedizione e' stata consegnata") is (
        ParcelStatus.DELIVERED
    )
    assert map_parcel_status("La spedizione è stata consegnata") is (
        ParcelStatus.DELIVERED
    )
    assert "Unrecognised" not in caplog.text


def test_collection_wordings_share_one_prefix(caplog):
    """Both observed "available for collection" sentences are a pickup point."""
    for text in (
        "disponibile per il ritiro dal giorno lavorativo successivo alla data indicata",
        "disponibile per il ritiro entro i termini indicati su sms/email",
    ):
        assert map_parcel_status(text) is ParcelStatus.AT_PICKUP_POINT
    assert "Unrecognised" not in caplog.text


def test_taken_in_charge_by_an_operator_is_registered(caplog):
    assert map_parcel_status("da un nostro operatore") is ParcelStatus.REGISTERED
    assert "Unrecognised" not in caplog.text


def test_pickup_point_comes_from_the_office_fields():
    """A Punto Poste names itself in structured fields."""
    events = [
        {
            "statoLavorazione": "la spedizione è stata presa in carico presso il Punto Poste",
            "luogo": "TABACCHERIA N. 7 VIA PIAVE 6, 71011 APRICENA (FG)",
            "denominazioneUfficio": "TABACCHERIA N. 7",
            "indirizzoUfficio": "VIA PIAVE 6",
        }
    ]
    assert pickup_point(events) == "TABACCHERIA N. 7, VIA PIAVE 6"


def test_pickup_point_accepts_a_post_office_named_in_luogo():
    events = [
        {
            "statoLavorazione": "disponibile per il ritiro",
            "luogo": "Ufficio Postale FIRENZE 1 VIA GIUSEPPE GALLIANO 27, 50144 FIRENZE (FI)",
        }
    ]
    assert pickup_point(events).startswith("Ufficio Postale FIRENZE 1")


def test_pickup_point_ignores_a_sorting_centre(caplog):
    """Poste fills the office fields on its own depots too."""
    events = [
        {
            "statoLavorazione": "la spedizione è in transito",
            "luogo": "BOLOGNA CMP WINDOWS, VIA ZANARDI 32",
            "denominazioneUfficio": "BOLOGNA CMP WINDOWS",
            "indirizzoUfficio": "VIA ZANARDI 32",
        }
    ]
    assert pickup_point(events) is None


def test_pickup_point_never_reads_a_home_address_from_luogo():
    """luogo on an ordinary delivery is the recipient's own address."""
    events = [{"statoLavorazione": "la spedizione è stata consegnata",
               "luogo": "VIA QUALCHE STRADA 12, 00100 ROMA (RM)"}]
    assert pickup_point(events) is None
    assert pickup_point([]) is None
    assert pickup_point(None) is None
    assert pickup_point([None, "x"]) is None


def test_pickup_flag_follows_the_awaiting_pickup_status():
    raw = {
        "listaMovimenti": [
            {
                "statoLavorazione": "disponibile per il ritiro entro i termini indicati su sms/email",
                "luogo": "Ufficio Postale ROMA 1 VIA X 1, 00100 ROMA (RM)",
                "dataOra": 1784541397000,
            }
        ]
    }
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"].startswith("Ufficio Postale ROMA 1")


# ---------------------------------------------------------------------------
# edge cases the happy path never reaches
# ---------------------------------------------------------------------------


def test_map_parcel_status_is_silent_without_a_status(caplog):
    """A not-yet-scanned parcel is unknown, not a thing to report."""
    assert map_parcel_status(None) is ParcelStatus.UNKNOWN
    assert map_parcel_status("") is ParcelStatus.UNKNOWN
    assert "Unrecognised" not in caplog.text


def test_to_iso_timestamp_handles_epochs_and_nonsense():
    assert to_iso_timestamp(None) is None
    # Poste stamps in epoch milliseconds.
    assert to_iso_timestamp(1784541397000).startswith("2026-")
    assert to_iso_timestamp(10**20) is None
    assert to_iso_timestamp("already a string") == "already a string"


def test_parse_delivery_estimate_refuses_what_it_cannot_read():
    assert parse_delivery_estimate(None) == (None, None)
    assert parse_delivery_estimate("nothing date-shaped here") == (None, None)
    # Matches the sentence, but names no month Poste uses.
    assert parse_delivery_estimate("consegna prevista 31 smarzo 2026") == (None, None)
    # Matches, names a real month, but is not a real date.
    assert parse_delivery_estimate("consegna prevista 31 febbraio 2026") == (
        None,
        None,
    )
    assert parse_delivery_estimate("consegna prevista entro 11 agosto 2026") == (
        "2026-08-11T00:00:00+02:00",
        "2026-08-11T23:59:59.999999+02:00",
    )


def test_format_dimensions_needs_all_three_sides():
    assert format_dimensions(None, 2, 3) is None
    assert format_dimensions(1, None, 3) is None
    assert format_dimensions(1, 2, None) is None
    assert format_dimensions(35, 31, 7) == {
        "length": 35,
        "width": 31,
        "height": 7,
        "text": "35 x 31 x 7 cm",
    }


def test_build_history_skips_entries_it_cannot_place():
    history = build_history(
        [
            "not a dict",
            {"statoLavorazione": "in data", "dataOra": None},
            {"statoLavorazione": "in data", "dataOra": 1784541397000},
            {"statoLavorazione": "in data", "dataOra": "not a date"},
        ]
    )
    # The dated one is kept; the undated one is dropped and the unparseable
    # one sorts to the end.
    assert len(history) == 2
    assert history[0]["timestamp"].startswith("2026-")


def test_normalize_parcel_ignores_a_non_dict_event():
    parcel = normalize_parcel(
        {"listaMovimenti": ["nope", {"statoLavorazione": "in data", "dataOra": 1}]}
    )
    assert parcel["status"] is ParcelStatus.IN_TRANSIT


def test_pickup_point_ignores_a_non_string_status():
    assert pickup_point([{"statoLavorazione": 7, "denominazioneUfficio": "X"}]) is None
