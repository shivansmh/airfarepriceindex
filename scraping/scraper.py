from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=False
    )
    page = browser.new_page()
    page.goto("https://in.via.com/flight/search?returnType=one-way&destination=BOM&bdestination=BOM&destinationL=Mumbai,Mumbai&destinationCity=Mumbai&destinationCN=India&source=DEL&bsource=DEL&sourceL=Delhi,Delhi&sourceCity=Delhi&sourceCN=India&month=9&day=18&year=2026&date=9/18/2026&numAdults=1&numChildren=0&numInfants=0&validation_result=&domesinter=international&livequote=-1&flightClass=ALL&travType=INTL&routingType=ALL&preferredCarrier=&prefCarrier=0&isAjax=false")

    page.locator(".result").first.wait_for()
    page.wait_for_timeout(2000)

    flights = page.locator(".result").all()

    date_ver = page.locator(".dateLabl .dt")
    date = date_ver.inner_text() if date_ver else None
    print("Date:", date)

    route_from_ver = page.locator(".labl.onw .airpt")
    route_from = route_from_ver.inner_text() if route_from_ver else None
    route_to_ver = page.locator(".labl.dest .airpt")
    route_to = route_to_ver.inner_text() if route_to_ver else None
    print("Route:", route_from, "to", route_to)

    for flight in flights:
        airline_ver=flight.locator(".airDet .name")
        name_ver=flight.locator(".airDet .fltNum")
        dep_time_ver=flight.locator(".depTime .time")
        dep_city_ver=flight.locator(".depTime .city")
        arr_time_ver=flight.locator(".arrTime .time")
        arr_city_ver=flight.locator(".arrTime .city")
        price_ver=flight.locator(".colCont .price")

        airline = airline_ver.inner_text() if airline_ver else None
        name = name_ver.inner_text() if name_ver else None
        dep_time = dep_time_ver.inner_text() if dep_time_ver else None
        dep_city = dep_city_ver.inner_text() if dep_city_ver else None
        arr_time = arr_time_ver.inner_text() if arr_time_ver else None
        arr_city = arr_city_ver.inner_text() if arr_city_ver else None
        price = price_ver.inner_text() if price_ver else None


        print(airline, name,":", dep_city, dep_time, "to", arr_city, arr_time, "Price: Rs.", price)
        page.wait_for_timeout(3000)
    browser.close()