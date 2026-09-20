from via.scraping.flight_scraper_multiplecities import airline_label, airline_names, parse_via_api_response, parse_via_rows, select_routes


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


def test_structured_api_parser_uses_nested_fares_and_cheapest_variant():
    payload = {
        "onwardJourneys": [
            {"fares": {"totalFare": {"total": {"amount": 7000}, "base": {"amount": 5000}, "tax": {"amount": 2000}}}, "flights": [{"carrier": {"code": "6E", "name": "IndiGo"}, "flightNo": "123", "depDetail": {"time": "2026-10-20 08:00:00.000"}, "arrDetail": {"time": "2026-10-20 10:00:00.000"}}]},
            {"fares": {"totalFare": {"total": {"amount": 6400}, "base": {"amount": 4400}, "tax": {"amount": 2000}}}, "flights": [{"carrier": {"code": "6E", "name": "IndiGo"}, "flightNo": "123", "depDetail": {"time": "2026-10-20 08:00:00.000"}, "arrDetail": {"time": "2026-10-20 10:00:00.000"}}]},
        ]
    }
    result = parse_via_api_response(payload, "https://in.via.com/apiv2/flight/search")
    assert len(result.flights) == 1
    assert result.flights[0]["price"] == "₹6,400"
    assert result.flights[0]["base_fare"] == 4400
    assert result.flights[0]["taxes"] == 2000


def test_select_routes_prioritizes_highest_passenger_volume():
    routes = [
        {"origin_code": "LOW", "destination_code": "AAA", "passengers": 10},
        {"origin_code": "HIGH", "destination_code": "BBB", "passengers": 100},
        {"origin_code": "MID", "destination_code": "CCC", "passengers": 50},
    ]
    selected = select_routes(routes, top_routes=2)
    assert [(route["origin_code"], route["passengers"]) for route in selected] == [("HIGH", 100), ("MID", 50)]


if __name__ == "__main__":
    test_known_airlines()
    test_mixed_carrier_connection_preserves_both_names()
    test_scraped_row_contains_airline()
    test_structured_api_parser_uses_nested_fares_and_cheapest_variant()
    print("airline extraction checks passed")
