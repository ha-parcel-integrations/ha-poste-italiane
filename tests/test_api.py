"""Tests for the Poste Italiane API client."""
import json
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from custom_components.poste_italiane.api import (
    PosteItalianeApiClient,
    PosteItalianeApiError,
)

CODE = "CW000000000IT"


def _session_returning(status: int, body: object = None) -> MagicMock:
    response = AsyncMock()
    response.status = status
    if isinstance(body, str):
        response.json = AsyncMock(side_effect=json.JSONDecodeError("x", body, 0))
    else:
        response.json = AsyncMock(return_value=body)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=ctx)
    return session


async def test_get_parcel_returns_parcel_on_success():
    session = _session_returning(
        200, {"esitoRicerca": "3", "idTracciatura": CODE}
    )
    client = PosteItalianeApiClient(session)

    parcel = await client.async_get_parcel(CODE)

    assert parcel["idTracciatura"] == CODE
    assert session.post.call_args.args[0].endswith("/ricercasemplice")
    assert session.post.call_args.kwargs["json"] == {
        "codiceSpedizione": CODE, "tipoRichiedente": "WEB", "periodoRicerca": 1
    }
    assert session.post.call_args.kwargs["headers"]["Origin"] == "https://www.poste.it"
    assert session.post.call_args.kwargs["headers"]["Referer"] == "https://www.poste.it/"


async def test_get_parcel_returns_none_when_not_found():
    """An unknown or not-yet-scanned code is a normal state, not an error."""
    client = PosteItalianeApiClient(
        _session_returning(200, {"esitoRicerca": "2"})
    )
    assert await client.async_get_parcel("EXAMPLE000000") is None


async def test_get_parcel_returns_none_for_the_invalid_code_envelope():
    client = PosteItalianeApiClient(
        _session_returning(200, {"esitoRicerca": "1", "stato": "1", "idTracciatura": "1234567890"})
    )
    assert await client.async_get_parcel("1234567890") is None


async def test_get_parcel_raises_on_hollow_success():
    """A success envelope needs the carrier's resolved tracking code."""
    client = PosteItalianeApiClient(
        _session_returning(200, {"esitoRicerca": "3"})
    )
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_error_status():
    client = PosteItalianeApiClient(_session_returning(500, {}))
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_http_400():
    client = PosteItalianeApiClient(_session_returning(400, {}))
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unparseable_body():
    client = PosteItalianeApiClient(_session_returning(200, "not json"))
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_non_object_body():
    client = PosteItalianeApiClient(_session_returning(200, ["not", "a", "dict"]))
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_raises_on_unknown_error_envelope():
    client = PosteItalianeApiClient(
        _session_returning(200, {"esitoRicerca": "unexpected"})
    )
    with pytest.raises(PosteItalianeApiError) as err:
        await client.async_get_parcel(CODE)
    assert "unexpected response envelope" in str(err.value)


async def test_get_parcel_raises_on_error_envelope_without_detail():
    client = PosteItalianeApiClient(_session_returning(200, {}))
    with pytest.raises(PosteItalianeApiError):
        await client.async_get_parcel(CODE)


async def test_get_parcel_warns_once_for_an_unknown_shape(caplog):
    client = PosteItalianeApiClient(_session_returning(200, {"newEnvelope": "value"}))
    for _ in range(2):
        with pytest.raises(PosteItalianeApiError):
            await client.async_get_parcel(CODE)
    assert caplog.text.count("unrecognised response shape") == 1
    assert CODE not in caplog.text
    assert "issues/new?template=unrecognised_status.yml" in caplog.text


async def test_get_parcel_propagates_network_error():
    """ClientError is left alone — DataUpdateCoordinator already wraps it."""
    session = MagicMock()
    session.post = MagicMock(side_effect=aiohttp.ClientError("boom"))
    client = PosteItalianeApiClient(session)
    with pytest.raises(aiohttp.ClientError):
        await client.async_get_parcel(CODE)
