from scraping.makemytrip_scraper_multiplecities import mmt_url, parse_card


def test_makemytrip_url_contains_route_and_date():
    assert "DEL-BOM-20260921" in mmt_url("DEL", "BOM", __import__("datetime").date(2026, 9, 21))
    assert "tripType=O" in mmt_url("DEL", "BOM", __import__("datetime").date(2026, 9, 21))


def test_parse_rendered_card_extracts_core_fields():
    row = parse_card("IndiGo 6E-1234 08:00 10:15 Delhi Mumbai ₹5,432")
    assert row["flight_number"] == "6E-1234"
    assert row["departure_time"] == "08:00"
    assert row["arrival_time"] == "10:15"
    assert row["price"] == "₹5,432"


if __name__ == "__main__":
    test_makemytrip_url_contains_route_and_date()
    test_parse_rendered_card_extracts_core_fields()
    print("MakeMyTrip parser checks passed")
