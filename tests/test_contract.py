"""The parcel contract's checks, run over every normalised sample."""

from datetime import datetime

import pytest

from custom_components.poste_italiane.const import ParcelStatus
from custom_components.poste_italiane.parcels import normalize_parcel, parse_iso

from .payloads import active_sample, crono_sample, delivered_sample, movement

CANONICAL_KEYS = [
    "carrier",
    "barcode",
    "sender",
    "receiver",
    "contents",
    "status",
    "raw_status",
    "delivered",
    "delivered_at",
    "planned_from",
    "planned_to",
    "pickup",
    "pickup_point",
    "url",
    "weight",
    "dimensions",
    "history",
    "raw",
]

READY = "disponibile per il ritiro entro i termini indicati su sms/email"
ESTIMATE = "Consegna prevista entro Giovedì 1 Gennaio 2026"


def _ready() -> dict:
    return {
        "idTracciatura": "PI000000001IT",
        "stato": "4",
        "dataPrevistaConsegna": ESTIMATE,
        "listaMovimenti": [
            movement("la spedizione è in transito presso il Centro", 1767100000000),
            {
                **movement(READY, 1767200000000),
                "denominazioneUfficio": "UFFICIO POSTALE ESEMPIO",
                "indirizzoUfficio": "VIA ESEMPIO 1",
            },
        ],
    }


def _collected() -> dict:
    raw = _ready()
    raw["stato"] = "5"
    raw["listaMovimenti"].append(
        movement("la spedizione è stata consegnata", 1767300000000)
    )
    return raw


def _returning() -> dict:
    raw = _ready()
    raw["listaMovimenti"].append(movement("in restituzione al mittente", 1767300000000))
    return raw


def _flag_on_returning() -> dict:
    raw = _returning()
    raw["stato"] = "5"
    return raw


def _problem() -> dict:
    raw = active_sample()
    raw["listaMovimenti"].append(
        movement("consegna non andata a buon fine", 1767300000000)
    )
    return raw


SAMPLES = {
    "delivered": delivered_sample,
    "active": active_sample,
    "crono": crono_sample,
    "at_pickup_point": _ready,
    "collected": _collected,
    "returning": _returning,
    "flag_on_returning": _flag_on_returning,
    "problem": _problem,
    "bare": lambda: {"idTracciatura": "PI000000002IT"},
}


@pytest.fixture(params=SAMPLES)
def parcel(request) -> dict:
    return normalize_parcel(SAMPLES[request.param]())


def test_keys_and_order(parcel):
    assert list(parcel) == CANONICAL_KEYS


def test_delivered_follows_status(parcel):
    assert parcel["delivered"] is (parcel["status"] is ParcelStatus.DELIVERED)


def test_delivered_at_only_when_delivered(parcel):
    if not parcel["delivered"]:
        assert parcel["delivered_at"] is None


def test_planned_window_is_ordered_and_anchored(parcel):
    if parcel["planned_to"] is not None:
        assert parcel["planned_from"] is not None
        assert parse_iso(parcel["planned_to"]) > parse_iso(parcel["planned_from"])


def test_planned_is_empty_when_the_parcel_is_done_or_waiting(parcel):
    if parcel["status"] in (
        ParcelStatus.DELIVERED,
        ParcelStatus.AT_PICKUP_POINT,
        ParcelStatus.RETURNING,
    ):
        assert parcel["planned_from"] is None
        assert parcel["planned_to"] is None


def test_pickup_is_a_bool_and_the_point_needs_it(parcel):
    assert isinstance(parcel["pickup"], bool)
    if not parcel["pickup"]:
        assert parcel["pickup_point"] is None


def test_the_delivered_flag_does_not_override_a_return():
    parcel = normalize_parcel(_flag_on_returning())
    assert parcel["status"] is ParcelStatus.RETURNING
    assert parcel["delivered"] is False
    assert parcel["delivered_at"] is None


def test_the_delivered_flag_wins_over_a_pickup_point_event():
    raw = _ready()
    raw["stato"] = "5"
    parcel = normalize_parcel(raw)
    assert parcel["status"] is ParcelStatus.DELIVERED
    assert parcel["delivered"] is True
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "UFFICIO POSTALE ESEMPIO"
    assert parcel["planned_from"] is None


def test_a_parcel_at_a_pickup_point_names_it_without_the_address():
    parcel = normalize_parcel(_ready())
    assert parcel["status"] is ParcelStatus.AT_PICKUP_POINT
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "UFFICIO POSTALE ESEMPIO"


def test_a_collected_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_collected())
    assert parcel["delivered"] is True
    assert parcel["delivered_at"] is not None
    assert parcel["pickup"] is True
    assert parcel["pickup_point"] == "UFFICIO POSTALE ESEMPIO"


def test_a_returning_pickup_parcel_stays_pickup():
    parcel = normalize_parcel(_returning())
    assert parcel["pickup"] is True


def test_a_home_delivery_is_not_pickup():
    parcel = normalize_parcel(delivered_sample())
    assert parcel["pickup"] is False
    assert parcel["pickup_point"] is None


def test_a_date_covers_the_whole_local_day():
    parcel = normalize_parcel(active_sample())
    start = datetime.fromisoformat(parcel["planned_from"])
    end = datetime.fromisoformat(parcel["planned_to"])
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert (end.hour, end.minute, end.second, end.microsecond) == (23, 59, 59, 0)
    assert start.date() == end.date()
    assert start.utcoffset().total_seconds() == 3600
