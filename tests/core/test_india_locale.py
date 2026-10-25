"""Indian locale: money/date formatting and the synthetic customers' addresses and phone numbers."""
import re
from datetime import date

from backend.shared.formatting import format_date, format_datetime, format_money, format_money_compact, group_number
from config.loader import india


def test_indian_money_and_number_formatting():
    assert format_money("1234567.50") == "₹12,34,567.50"
    assert format_money(14999) == "₹14,999"
    assert format_money("999.00") == "₹999"
    assert format_money(-1680) == "−₹1,680"
    assert group_number(123456789) == "12,34,56,789"
    assert format_money_compact(450000) == "₹4.5 L" and format_money_compact(13000000) == "₹1.3 Cr"


def test_dates_use_store_time_zone():
    # 20:30 UTC is already the next day in India (UTC+5:30)
    assert format_datetime("2026-10-21T20:30:00Z") == "22 Oct 2026, 02:00"
    assert format_date(date(2026, 1, 5)) == "5 Jan 2026"


def test_generated_customers_have_valid_indian_addresses():
    from ai.generators import generate_world
    places = india()
    pins = {pin for c in places["cities"] for _, pin in c["localities"]}
    states = set(places["states_and_union_territories"])
    w = generate_world(today=date(2026, 10, 21), scale=0.05)
    for c in w.customers.itertuples():
        for pin, state, city in ((c.postal, c.state, c.city), (c.alt_postal, c.alt_state, c.alt_city)):
            assert re.fullmatch(places["pin_code_pattern"], pin) and pin in pins
            assert state in states
            assert any(x["city"] == city and x["state"] == state for x in places["cities"])
        assert re.fullmatch(places["mobile_pattern"], c.phone)
        assert c.first_name in places["first_names"] and c.last_name in places["last_names"]
    # Shelf prices end in 9 (₹249, ₹1,299, ₹14,999)
    assert all(str(int(p)).endswith("9") for p in w.products["price"])
