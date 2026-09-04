import json
import os
import statistics
from datetime import datetime
from pathlib import Path

# --- 1. Configuration & Weights ---
WINDOW_WEIGHTS = {
    "T_plus_45": 0.15,
    "T_plus_30": 0.20,
    "T_plus_15": 0.30,
    "T_plus_7": 0.30,
    "T_plus_1": 0.05,
}

ROUTE_WEIGHTS = {
    "Delhi - Bengaluru": 0.30,
    "Delhi - Bombay": 0.40,
    "Calcutta - Bombay": 0.30,
}

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_FILE = Path(os.getenv("BASE_FILE", str(REPO_ROOT / "data" / "base_day.txt"))).expanduser()
TARGET_FILE = Path(os.getenv("TARGET_FILE", str(REPO_ROOT / "dashboard" / "target_day.txt"))).expanduser()
JSON_OUTPUT = Path(os.getenv("JSON_OUTPUT", str(REPO_ROOT / "dashboard" / "apix_output.json"))).expanduser()


def parse_and_calculate_medians(filepath):
    """Read a scraper text report and calculate median prices by route/window."""
    route_data = {}
    current_route = None
    current_window = None

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Could not find the file: {filepath}")

    with open(filepath, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()

            if line.startswith("ROUTE:"):
                current_route = line.split("ROUTE:", 1)[1].strip()
                route_data.setdefault(current_route, {})

            elif line.startswith("T_plus_"):
                current_window = line.split()[0].strip()
                if current_route:
                    route_data[current_route].setdefault(current_window, [])

            elif line.startswith("Price:") and current_route and current_window:
                try:
                    price_str = line.split("₹", 1)[-1]
                    clean_price = float(price_str.replace(",", "").strip())
                    route_data[current_route][current_window].append(clean_price)
                except (IndexError, ValueError):
                    pass

    route_medians = {}
    for route, windows in route_data.items():
        route_medians[route] = {}
        for window, prices in windows.items():
            if prices:
                median = statistics.median(prices)
                route_medians[route][window] = int(median) if isinstance(median, float) and median.is_integer() else median

    return route_medians


def calculate_apix(base_prices, target_prices):
    """Calculate APIx and return all intermediate and final values as a dictionary."""
    route_level_indices = {}
    route_details = {}
    warnings = []
    total_active_route_weight = 0.0

    for route, route_weight in ROUTE_WEIGHTS.items():
        if route not in base_prices:
            warnings.append(f"Skipping '{route}': not found in base data.")
            continue
        if route not in target_prices:
            warnings.append(f"Skipping '{route}': not found in target data.")
            continue

        rli_sum = 0.0
        total_window_weight = 0.0
        window_details = {}

        for window, window_weight in WINDOW_WEIGHTS.items():
            base_price = base_prices[route].get(window)
            target_price = target_prices[route].get(window)

            if base_price is not None and target_price is not None and base_price != 0:
                price_relativity = (target_price / base_price) * 100
                weighted_contribution = window_weight * price_relativity
                rli_sum += weighted_contribution
                total_window_weight += window_weight
                window_details[window] = {
                    "weight": window_weight,
                    "base_median_price": base_price,
                    "target_median_price": target_price,
                    "price_relativity": round(price_relativity, 6),
                    "weighted_contribution": round(weighted_contribution, 6),
                }
            else:
                reason = "missing base or target median"
                if base_price == 0:
                    reason = "base median is zero"
                warnings.append(f"Missing or invalid data for '{route}' at '{window}': {reason}.")
                window_details[window] = {
                    "weight": window_weight,
                    "base_median_price": base_price,
                    "target_median_price": target_price,
                    "price_relativity": None,
                    "weighted_contribution": None,
                }

        if total_window_weight > 0:
            normalized_rli = rli_sum / total_window_weight
            route_level_indices[route] = round(normalized_rli, 6)
            total_active_route_weight += route_weight
            route_details[route] = {
                "route_weight": route_weight,
                "active_window_weight": round(total_window_weight, 6),
                "route_level_apix": round(normalized_rli, 6),
                "windows": window_details,
            }
        else:
            warnings.append(f"Could not calculate route-level APIx for '{route}': no valid window pairs.")
            route_details[route] = {
                "route_weight": route_weight,
                "active_window_weight": 0,
                "route_level_apix": None,
                "windows": window_details,
            }

    if route_level_indices:
        final_apix = sum(ROUTE_WEIGHTS[route] * rli for route, rli in route_level_indices.items())
        if 0 < total_active_route_weight < 1.0:
            final_apix /= total_active_route_weight
    else:
        final_apix = 0.0
        warnings.append("No routes could be evaluated; final daily APIx set to 0.0.")

    price_change = final_apix - 100
    direction = "rose" if price_change > 0 else "fell" if price_change < 0 else "was unchanged"

    return {
        "base_medians": base_prices,
        "target_medians": target_prices,
        "window_weights": WINDOW_WEIGHTS,
        "route_weights": ROUTE_WEIGHTS,
        "route_level_apix": route_level_indices,
        "route_details": route_details,
        "active_route_weight": round(total_active_route_weight, 6),
        "daily_apix": round(final_apix, 6),
        "price_change_from_base_percent": round(price_change, 6),
        "direction": direction,
        "warnings": warnings,
    }


def print_summary(result):
    print("\n--- APIx SUMMARY ---")
    print(f"Base routes found:   {list(result['base_medians'].keys())}")
    print(f"Target routes found: {list(result['target_medians'].keys())}")
    print("\n--- ROUTE-LEVEL APIx ---")
    for route, value in result["route_level_apix"].items():
        print(f"{route}: {value:.4f}")
    print("\n--- FINAL DAILY APIx ---")
    print(f"Final Daily APIx: {result['daily_apix']:.2f}")
    print(f"Significance: The overall price index {result['direction']} by {abs(result['price_change_from_base_percent']):.2f}% relative to the base day.")
    if result["warnings"]:
        print("\nWarnings:")
        for warning in result["warnings"]:
            print(f"- {warning}")


if __name__ == "__main__":
    try:
        base_medians = parse_and_calculate_medians(BASE_FILE)
        target_medians = parse_and_calculate_medians(TARGET_FILE)
        result = calculate_apix(base_medians, target_medians)

        # write_text replaces the previous JSON file on every run.
        JSON_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        JSON_OUTPUT.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now().isoformat(timespec="seconds"),
                    "base_file": str(BASE_FILE),
                    "target_file": str(TARGET_FILE),
                    "json_output_file": str(JSON_OUTPUT),
                    **result,
                },
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )

        print_summary(result)
        print(f"\nJSON output saved to: {JSON_OUTPUT}")

    except FileNotFoundError as error:
        print(f"Error: {error}")
    except Exception as error:
        print(f"Unexpected error: {error}")
