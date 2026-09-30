"""Country and currency identifiers for target-side party masters.

These identifiers describe the party; they do not determine tax or FX treatment.
"""

from __future__ import annotations

from decimal import Decimal

import pycountry


GCC_COUNTRY_CODES = frozenset({"AE", "BH", "KW", "OM", "QA", "SA"})
GCC_CURRENCY_SUGGESTIONS = {
    "AE": "AED", "BH": "BHD", "KW": "KWD", "OM": "OMR", "QA": "QAR", "SA": "SAR",
}

# Quotation currencies are deliberately narrower than the party-master
# catalogue. Other currencies require a reviewed minor-unit rule first.
QUOTATION_CURRENCY_MINOR_UNITS = {
    "AED": 2, "USD": 2, "EUR": 2, "GBP": 2, "SAR": 2, "QAR": 2,
    "BHD": 3, "KWD": 3, "OMR": 3,
}


def quotation_money_quantum(value: str) -> Decimal:
    code = currency_code(value)
    digits = QUOTATION_CURRENCY_MINOR_UNITS.get(code)
    if digits is None:
        raise ValueError(f"Quotation currency {code} is not enabled for controlled pricing")
    return Decimal(1).scaleb(-digits)


def country_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 2 or pycountry.countries.get(alpha_2=code) is None:
        raise ValueError("Choose a valid two-letter country code")
    return code


def currency_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != 3 or pycountry.currencies.get(alpha_3=code) is None:
        raise ValueError("Choose a valid three-letter currency code")
    return code


def market_scope(code: str | None) -> str:
    if not code:
        return "unverified"
    if code == "AE":
        return "uae"
    return "gcc" if code in GCC_COUNTRY_CODES else "international"


def country_catalog() -> dict:
    countries = sorted(({"code": row.alpha_2, "name": row.name,
                         "market_scope": market_scope(row.alpha_2),
                         "currency_suggestion": GCC_CURRENCY_SUGGESTIONS.get(row.alpha_2)}
                        for row in pycountry.countries), key=lambda row: row["name"])
    currencies = sorted(({"code": row.alpha_3, "name": row.name}
                         for row in pycountry.currencies), key=lambda row: row["code"])
    return {"countries": countries, "currencies": currencies}
