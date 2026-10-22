"""Canonical parcel shape, status mapping and list helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry

from .const import (
    CONF_DELIVERED_FILTER_AMOUNT,
    CONF_DELIVERED_FILTER_TYPE,
    DEFAULT_DELIVERED_FILTER_AMOUNT,
    DEFAULT_DELIVERED_FILTER_TYPE,
    HISTORY_MAX_EVENTS,
    TRACKING_URL,
    ParcelStatus,
)

_LOGGER = logging.getLogger(__name__)

# Built once at import: constructing a ZoneInfo reads the tz file from disk.
CARRIER_TZ = ZoneInfo("Europe/Rome")

# Where users report a status we do not map yet. Rewritten by the bootstrap
# script; it must point at the carrier's own repo so the log line is
# copy-pasteable straight into a new issue.
#
# The ``?template=`` parameter matters: without it the link opens a blank form,
# and the report comes back missing the version and the log line we need.
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-poste-italiane/issues/new"
    "?template=unrecognised_status.yml"
)

_STATUS_MAP: dict[str, ParcelStatus] = {
    "la spedizione è in consegna": ParcelStatus.OUT_FOR_DELIVERY,
    "la spedizione è stata consegnata": ParcelStatus.DELIVERED,
    "all'estero": ParcelStatus.IN_TRANSIT,
    "presso il paese estero in data": ParcelStatus.IN_TRANSIT,
    "in data": ParcelStatus.IN_TRANSIT,
    "con successo in data": ParcelStatus.DELIVERED,
    "sono in corso delle verifiche sulla spedizione. contatta assistenza": ParcelStatus.PROBLEM,
    "disponibile per il ritiro dal giorno lavorativo successivo alla data indicata": ParcelStatus.AT_PICKUP_POINT,
    "a seguito di acquisto da poste.it": ParcelStatus.REGISTERED,
}

# Status codes we have already warned about, so each unmapped one is logged
# only once per HA session instead of on every poll.
_unmapped_statuses_logged: set[str] = set()

_ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}
_ITALIAN_DELIVERY_DATE_RE = re.compile(
    r"(?:consegna prevista(?: entro)?\s+)(?:\w+\s+)?(\d{1,2})\s+"
    r"([a-zà]+)\s+(\d{4})",
    re.IGNORECASE,
)


def _warn_unmapped_status(code: str) -> None:
    """Log an unmapped carrier status once, with a copy-paste issue link."""
    if code in _unmapped_statuses_logged:
        return
    _unmapped_statuses_logged.add(code)
    _LOGGER.warning(
        "Unrecognised Poste Italiane status — help us map it. Open an issue "
        "and paste this line: %s\n  status=%s → reported as 'unknown'",
        NEW_ISSUE_URL,
        code,
    )


def map_parcel_status(code: str | None) -> ParcelStatus:
    """Map a carrier status code to a canonical :class:`ParcelStatus`.

    ``None`` (a not-yet-scanned parcel) reports ``unknown`` silently; an
    unrecognised code reports ``unknown`` with a one-shot warning.
    """
    if not code:
        return ParcelStatus.UNKNOWN
    normalized = " ".join(str(code).casefold().split())
    # Poste writes "è" as the ASCII "e'" on some responses — the same sentence
    # arrived both ways — so a delivered parcel would otherwise fall to
    # unknown purely on typography.
    normalized = re.sub(r"\be'(?=\s)", "è", normalized)
    if normalized.startswith("la spedizione è stata presa in carico"):
        return ParcelStatus.REGISTERED
    if normalized.startswith("da un nostro operatore"):
        return ParcelStatus.REGISTERED
    if normalized.startswith("disponibile per il ritiro"):
        return ParcelStatus.AT_PICKUP_POINT
    if normalized.startswith("la spedizione è in transito"):
        return ParcelStatus.IN_TRANSIT
    if normalized.startswith("completata la fase di verifica per lo svincolo"):
        return ParcelStatus.IN_TRANSIT
    # Two confirmed variants both start this way — a bad address, and a
    # "will retry next business day" notice — so the prefix alone is enough
    # to catch further wording variants of the same failed-attempt family.
    if normalized.startswith("consegna non andata a buon fine"):
        return ParcelStatus.PROBLEM
    if normalized.startswith("in restituzione al mittente"):
        return ParcelStatus.RETURNING
    mapped = _STATUS_MAP.get(normalized)
    if mapped is not None:
        return mapped
    _warn_unmapped_status(str(code))
    return ParcelStatus.UNKNOWN


def map_event_status(code: str | None) -> ParcelStatus:
    """Map a history status, retaining unmapped carrier text as ``unknown``."""
    return map_parcel_status(code)


def parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO 8601 string to an aware datetime, or ``None`` on failure.

    Naive values are treated as UTC so a list always sorts without crashing on
    a mixed set.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def to_iso_timestamp(value: Any) -> str | None:
    """Return an ISO 8601 string for an API timestamp field.

    Numbers are treated as **epoch milliseconds** — the common case for the
    consumer APIs in this suite. Strings pass through untouched; their
    consumers are guarded by :func:`parse_iso`. Adjust the numeric branch if
    your carrier stamps in seconds.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return str(value)


def parse_delivery_estimate(value: str | None) -> tuple[str | None, str | None]:
    """Convert Poste's Italian ``dataPrevistaConsegna`` text to a local-day window."""
    match = _ITALIAN_DELIVERY_DATE_RE.search(value or "")
    if match is None:
        return None, None
    day, month_name, year = match.groups()
    month = _ITALIAN_MONTHS.get(month_name.casefold())
    if month is None:
        return None, None
    try:
        start = datetime(int(year), month, int(day), tzinfo=CARRIER_TZ)
    except ValueError:
        return None, None
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    return start.isoformat(), end.isoformat()


def format_dimensions(
    length: float | None, width: float | None, height: float | None
) -> dict[str, Any] | None:
    """Return the canonical ``dimensions`` dict, or ``None`` when incomplete.

    Units contract: **centimetres**, with ``text`` pre-formatted as
    ``"L x W x H cm"`` (integer values, lowercase ``x``) so dashboards can show
    a dimension without doing their own formatting. Convert before calling if
    the carrier reports millimetres or inches.
    """
    if length is None or width is None or height is None:
        return None
    return {
        "length": length,
        "width": width,
        "height": height,
        "text": f"{int(length)} x {int(width)} x {int(height)} cm",
    }


def build_history(
    events: list | None, *, max_events: int = HISTORY_MAX_EVENTS
) -> list[dict]:
    """Build the canonical ``history`` list from the carrier's event list.

    Each entry is ``{timestamp, status, raw_status}`` — identical across all
    suite carriers, and top-level (not under ``raw``) so it survives the
    aggregator's ``strip_raw()``. ``raw_status`` is the carrier's own text, or
    its event code when the API has no human-readable text. Sorted oldest →
    newest and capped to the most recent ``max_events``.

    """
    parseable: list[tuple[datetime, dict]] = []
    unparseable: list[dict] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        timestamp = to_iso_timestamp(event.get("dataOra"))
        if not timestamp:
            continue
        entry = {
            "timestamp": timestamp,
            "status": map_event_status(event.get("statoLavorazione")),
            "raw_status": event.get("statoLavorazione"),
        }
        parsed = parse_iso(timestamp)
        if parsed is None:
            unparseable.append(entry)
        else:
            parseable.append((parsed, entry))
    parseable.sort(key=lambda item: item[0])
    ordered = [entry for _, entry in parseable] + unparseable
    return ordered[-max_events:]


def tracking_url(tracking_code: str | None) -> str | None:
    """Construct the consumer tracking deep-link for a parcel."""
    if not tracking_code:
        return None
    return TRACKING_URL.format(tracking_code=tracking_code)


# Wording that means the parcel is at, or was handed over at, a place the
# recipient collects it from. The office fields alone are not enough: Poste
# fills them on its own sorting centres too ("BOLOGNA CMP", "ANCONA RECAPITO"),
# so a parcel delivered to the door would otherwise name a depot as its pickup
# point.
_PICKUP_EVENT_PREFIXES = (
    "disponibile per il ritiro",
    "la spedizione è stata presa in carico presso il punto poste",
    "da un nostro operatore presso l'ufficio postale",
)


def _is_pickup_event(text: object) -> bool:
    """Whether an event's own wording places the parcel at a collection point."""
    if not isinstance(text, str):
        return False
    normalised = " ".join(text.casefold().split())
    normalised = re.sub(r"\be'(?=\s)", "è", normalised)
    return normalised.startswith(_PICKUP_EVENT_PREFIXES)


def pickup_point(events: list | None) -> str | None:
    """Return the collection point named on the newest collection event.

    Only events whose own wording says the parcel is collectable are read, and
    from those only the structured office fields plus a ``luogo`` Poste itself
    labels an ``Ufficio Postale``. ``luogo`` on an ordinary delivery event
    carries the recipient's own address, so it is never read blind.
    """
    for event in reversed(events or []):
        if not isinstance(event, dict):
            continue
        if not _is_pickup_event(event.get("statoLavorazione")):
            continue
        name = event.get("denominazioneUfficio")
        if isinstance(name, str) and name.strip():
            address = event.get("indirizzoUfficio")
            parts = [name.strip()]
            if isinstance(address, str) and address.strip():
                parts.append(address.strip())
            return ", ".join(parts)
        place = event.get("luogo")
        if isinstance(place, str) and place.strip().upper().startswith(
            "UFFICIO POSTALE"
        ):
            return place.strip()
    return None


def normalize_parcel(raw: dict, *, include_history: bool = False) -> dict:
    """Return a carrier-agnostic parcel dict with the payload under ``raw``.

    ``raw`` intentionally contains the complete, unmodified carrier response.
    Diagnostics redact its sensitive fields separately before they can be
    shared outside the installation.
    """
    tracking_code = raw.get("idTracciatura") or raw.get("trackingNumber")
    movements = raw.get("listaMovimenti")
    events = movements if isinstance(movements, list) else []
    latest_raw_status = None
    status = ParcelStatus.UNKNOWN
    delivered_at = None
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        event_status = event.get("statoLavorazione")
        if latest_raw_status is None:
            latest_raw_status = event_status
        mapped = map_parcel_status(event_status)
        if delivered_at is None and mapped is ParcelStatus.DELIVERED:
            delivered_at = to_iso_timestamp(event.get("dataOra"))
        if status is ParcelStatus.UNKNOWN and mapped is not ParcelStatus.UNKNOWN:
            status = mapped
    if str(raw.get("stato")) == "5":
        status = ParcelStatus.DELIVERED
    delivered = status is ParcelStatus.DELIVERED
    planned_from, planned_to = parse_delivery_estimate(raw.get("dataPrevistaConsegna"))

    return {
        "carrier": "Poste Italiane",
        "barcode": tracking_code,
        "sender": None,
        "receiver": None,
        "status": status,
        "raw_status": latest_raw_status or raw.get("stato"),
        "delivered": delivered,
        "delivered_at": delivered_at if delivered else None,
        "planned_from": None if delivered else planned_from,
        "planned_to": None if delivered else planned_to,
        "pickup": status is ParcelStatus.AT_PICKUP_POINT,
        "pickup_point": pickup_point(events),
        "url": tracking_url(tracking_code),
        "weight": None,
        "dimensions": None,
        "history": build_history(events) if include_history else None,
        "raw": raw,
    }


def sort_parcels_by_ts(
    parcels: list[dict], key_field: str, *, descending: bool = False
) -> list[dict]:
    """Return normalised parcels sorted by the ISO timestamp at ``key_field``.

    The suite's sort contract: incoming/outgoing ascending on ``planned_from``,
    delivered descending on ``delivered_at``. Parcels whose value is missing or
    unparseable always sort to the end, regardless of ``descending``.
    """
    with_ts: list[tuple[datetime, dict]] = []
    without_ts: list[dict] = []
    for parcel in parcels:
        parsed = parse_iso(parcel.get(key_field))
        if parsed is None:
            without_ts.append(parcel)
        else:
            with_ts.append((parsed, parcel))
    with_ts.sort(key=lambda item: item[0], reverse=descending)
    return [parcel for _, parcel in with_ts] + without_ts


def apply_delivered_filter(parcels: list[dict], entry: ConfigEntry) -> list[dict]:
    """Trim the delivered list per the entry's retention option.

    ``parcels`` must already be sorted newest-first. ``days`` keeps deliveries
    from the last N days (an unparseable ``delivered_at`` is kept rather than
    silently dropped); the ``parcels`` type keeps the N most recent. Parcels
    stay *tracked* either way — this only controls what the delivered sensor
    shows.
    """
    options = entry.options
    filter_type = options.get(CONF_DELIVERED_FILTER_TYPE, DEFAULT_DELIVERED_FILTER_TYPE)
    amount = int(
        options.get(CONF_DELIVERED_FILTER_AMOUNT, DEFAULT_DELIVERED_FILTER_AMOUNT)
    )
    if filter_type == "days":
        cutoff = datetime.now(UTC) - timedelta(days=amount)
        return [
            parcel
            for parcel in parcels
            if (parsed := parse_iso(parcel.get("delivered_at"))) is None
            or parsed >= cutoff
        ]
    return parcels[:amount]
