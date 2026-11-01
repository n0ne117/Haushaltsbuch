from datetime import date

import pytest

from app.fmt import amount_input, date_de, money, parse_amount


@pytest.mark.parametrize(
    "text, cents",
    [
        ("12", 1200),
        ("12,5", 1250),
        ("12,50", 1250),
        ("0,99", 99),
        (",5", 50),
        ("1.234,56", 123456),
        ("1234,56", 123456),
        ("12.50", 1250),  # dot-only keypad
        ("12.5", 1250),
        ("1.234", 123400),  # thousands separator
        ("1.234.567", 123456700),
        (" 7,00 € ", 700),
    ],
)
def test_parse_amount(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "0", "0,00", "-5", "abc", "1,234,5", "12,345", "1.23.4", "12.345.6"])
def test_parse_amount_rejects(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_money():
    assert money(123456) == "1.234,56 €"
    assert money(5) == "0,05 €"
    assert money(1250, "−") == "−12,50 €"


def test_amount_input_and_date():
    assert amount_input(123450) == "1234,50"
    assert date_de(date(2026, 3, 7)) == "07.03.2026"
