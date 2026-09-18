from scraping.flight_scraper_multiplecities import airline_label, airline_names, parse_via_rows


def test_known_airlines():
    assert airline_label("6E-1234") == "IndiGo"
    assert airline_label("AI-101") == "Air India"
    assert airline_label("QP-1820") == "Akasa Air"
    assert airline_label("IX-456") == "Air India Express"


def test_mixed_carrier_connection_preserves_both_names():
    assert airline_names("6E-1234,AI-456") == ["IndiGo", "Air India"]
    assert airline_label("6E-1234,AI-456") == "IndiGo, Air India"


def test_scraped_row_contains_airline():
    rows = parse_via_rows([
        "21:15 Delhi 5h 40m 1 Stop(s) DEL PNQ BLR 02:55 Bangalore IndiGo 6E-6673,6E-361 9 Seats Left Flight Details 8,491 Book"
    ])
    assert rows[0]["airline"] == "IndiGo"
    assert rows[0]["flight_number"] == "6E-6673,6E-361"


if __name__ == "__main__":
    test_known_airlines()
    test_mixed_carrier_connection_preserves_both_names()
    test_scraped_row_contains_airline()
    print("airline extraction checks passed")
