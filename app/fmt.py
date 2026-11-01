"""de-AT parsing and formatting of amounts and dates."""

import re
from datetime import date, datetime

from app.config import TZ

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = [
    "Jänner", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]

_THOUSANDS_DOTS = re.compile(r"^\d{1,3}(\.\d{3})+$")
_PLAIN = re.compile(r"^\d+(\.\d{1,2})?$")


def parse_amount(text: str) -> int:
    """Parse a user-entered amount into positive integer cents.

    Comma is the decimal separator; dots are thousands separators ("1.234,56").
    Without a comma, a dot followed by 1–2 digits is read as decimal point ("12.5"),
    so phones with a dot-only keypad still work.
    """
    s = text.strip().replace("€", "").replace(" ", "").replace(" ", "")
    if not s:
        raise ValueError("Bitte einen Betrag eingeben.")
    if "," in s:
        whole, _, frac = s.rpartition(",")
        if "," in whole or (whole and "." in whole and not _THOUSANDS_DOTS.match(whole)):
            raise ValueError("Ungültiger Betrag.")
        whole = whole.replace(".", "") or "0"
    elif _THOUSANDS_DOTS.match(s):
        whole, frac = s.replace(".", ""), ""
    elif _PLAIN.match(s):
        whole, _, frac = s.partition(".")
    else:
        raise ValueError("Ungültiger Betrag.")
    if not whole.isdigit() or (frac and not frac.isdigit()) or len(frac) > 2:
        raise ValueError("Ungültiger Betrag.")
    cents = int(whole) * 100 + int(frac.ljust(2, "0") or 0)
    if cents <= 0:
        raise ValueError("Der Betrag muss größer als 0 sein.")
    return cents


def _group(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def amount_input(cents: int) -> str:
    """Amount as it appears in an input field: 1234,5 → '1234,50'."""
    return f"{cents // 100},{cents % 100:02d}"


def money(cents: int, sign: str = "") -> str:
    """1234,56 € with optional explicit sign ('+' or '−')."""
    return f"{sign}{_group(abs(cents) // 100)},{abs(cents) % 100:02d} €"


def date_de(d: date) -> str:
    return d.strftime("%d.%m.%Y")


def day_heading(d: date) -> str:
    t = today()
    if d == t:
        prefix = "Heute"
    elif (t - d).days == 1:
        prefix = "Gestern"
    else:
        prefix = WEEKDAYS[d.weekday()]
    return f"{prefix}, {date_de(d)}"


def today() -> date:
    return datetime.now(TZ).date()
