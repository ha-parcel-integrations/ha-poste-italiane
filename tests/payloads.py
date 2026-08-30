"""Redacted Poste Italiane DoveQuando responses used by the test suite."""
from __future__ import annotations

ACTIVE_CODE = "LX000000000JP"
DELIVERED_CODE = "CW000000000IT"
CRONO_CODE = "9C0000J000000"


def movement(status: str, timestamp: int) -> dict:
    """Build a redacted carrier movement without a real place or address."""
    return {"statoLavorazione": status, "dataOra": timestamp, "luogo": "REDACTED"}


def delivered_sample(code: str = DELIVERED_CODE) -> dict:
    """PosteDelivery Europe response ending in delivery."""
    return {
        "esitoRicerca": "3", "idTracciatura": code,
        "tipoProdotto": "POSTEDELIVERY EUROPE", "tipoSpedizione": "P",
        "stato": "5", "flagRitorno": False,
        "listaMovimenti": [
            movement("la spedizione è stata presa in carico da un nostro operatore", 1767000000000),
            movement("la spedizione è in transito presso il Centro di lavorazione Internazionale", 1767100000000),
            movement("la spedizione è in consegna", 1767200000000),
            movement("la spedizione è stata consegnata", 1767300000000),
        ],
    }


def active_sample(code: str = ACTIVE_CODE) -> dict:
    """International express response with customs processing in transit."""
    return {
        "esitoRicerca": "3", "idTracciatura": code,
        "tipoProdotto": "EXPRES DA/PER ESTERO", "tipoSpedizione": "C",
        "stato": "4", "flagRitorno": False,
        "dataPrevistaConsegna": "Consegna prevista entro Giovedì 1 Gennaio 2026",
        "listaMovimenti": [
            movement("all'estero", 1767000000000),
            movement("completata la fase di verifica per lo svincolo presso il Centro di lavorazione Internazionale", 1767100000000),
            movement("la spedizione è in consegna", 1767200000000),
        ],
    }


def crono_sample(code: str = CRONO_CODE) -> dict:
    """Crono Plus response exercising the same public response envelope."""
    sample = delivered_sample(code)
    sample["tipoProdotto"] = "CRONO PLUS"
    return sample
