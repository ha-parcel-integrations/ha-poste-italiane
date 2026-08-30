"""Poste Italiane public tracking API client."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .const import TRACKING_API_URL

_LOGGER = logging.getLogger(__name__)
_unexpected_shapes_logged: set[tuple[str, ...]] = set()
NEW_ISSUE_URL = (
    "https://github.com/ha-parcel-integrations/ha-poste-italiane/issues/new"
    "?template=unrecognised_status.yml"
)


class PosteItalianeApiError(Exception):
    """Raised when a Poste Italiane API call returns an unexpected response."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        retry_after: float | None = None,
    ) -> None:
        """Store the status code and the ``Retry-After`` header, if any."""
        super().__init__(f"Poste Italiane API request failed: {detail}")
        self.detail = detail
        self.status_code = status_code
        self.retry_after = retry_after


class PosteItalianeApiClient:
    """Client for the public Poste Italiane tracking endpoint.

    No authentication: the endpoint is keyed on the tracking code alone.
    """

    def __init__(self, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an aiohttp session."""
        self._session = session

    async def async_get_parcel(self, tracking_code: str) -> dict[str, Any] | None:
        """Fetch one parcel's tracking details.

        Returns the parcel dict for a known parcel, or ``None`` when the
        endpoint reports the code as unknown — which is also what a
        not-yet-scanned parcel gets. Any other failure envelope or non-2xx
        status raises :class:`PosteItalianeApiError`; network errors propagate
        as ``aiohttp.ClientError``.
        """
        headers = {
            "Origin": "https://www.poste.it",
            "Referer": "https://www.poste.it/",
            "User-Agent": "Home Assistant Poste Italiane integration",
        }
        body = {
            "codiceSpedizione": tracking_code,
            "tipoRichiedente": "WEB",
            "periodoRicerca": 1,
        }
        async with self._session.post(TRACKING_API_URL, json=body, headers=headers) as response:
            if response.status == 429:
                retry_after_header = response.headers.get("Retry-After")
                try:
                    retry_after = float(retry_after_header) if retry_after_header else None
                except ValueError:
                    retry_after = None  # an HTTP-date, not seconds; let the caller's own backoff handle it
                raise PosteItalianeApiError(
                    "HTTP 429", status_code=429, retry_after=retry_after
                )
            if response.status != 200:
                raise PosteItalianeApiError(
                    f"HTTP {response.status}", status_code=response.status
                )
            try:
                # content_type=None: consumer endpoints routinely serve JSON as
                # text/plain, and aiohttp would otherwise refuse to parse it.
                payload = await response.json(content_type=None)
            except ValueError as err:
                raise PosteItalianeApiError(f"unparseable body ({err})") from err

        if not isinstance(payload, dict):
            raise PosteItalianeApiError("unexpected body (not a JSON object)")

        if payload.get("esitoRicerca") == "3" and payload.get("idTracciatura"):
            return payload
        if payload.get("esitoRicerca") in {"1", "2"}:
            return None
        shape = tuple(sorted(str(key) for key in payload))
        if shape not in _unexpected_shapes_logged:
            _unexpected_shapes_logged.add(shape)
            _LOGGER.warning(
                "Poste Italiane returned an unrecognised response shape; "
                "keys=%s. Please open an issue with diagnostics: %s",
                shape,
                NEW_ISSUE_URL,
            )
        raise PosteItalianeApiError("unexpected response envelope")
