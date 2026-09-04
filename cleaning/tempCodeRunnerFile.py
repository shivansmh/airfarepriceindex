import statistics
import os

# --- 1. Configuration & Weights ---
# Match these window keys to the headers in your text file (e.g., T_plus_1)
WINDOW_WEIGHTS = {
    "T_plus_45": 0.15,
    "T_plus_30": 0.20,
    "T_plus_15": 0.30,
    "T_plus_7": 0.30,
    "T_plus_1": 0.05
}

# EXACT strings matching the header after "ROUTE: " in your txt file
ROUTE_WEIGHTS = {
    "Delhi - Bengaluru": 0.30,
    "Delhi - Bombay": 0.40,
    "Calcutta - Bombay": 0.30
}

# --- 2. Data Parsing Engine ---
def parse_and_calculate_medians(filepath):
    """Reads the scraped text file and calculates median prices per route and window."""
    route_data = {}
    current_route = None
    current_window = None

    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Could not find the file: {filepath}")

    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            
            # Detect Route header (e.g., "ROUTE: Calcutta - Bombay")
            if line.startswith("ROUTE:"):
                # Extracts "Calcutta - Bombay"
                current_route = line.split("ROUTE:")[1].strip()
                if current_route not in route_data:
                    route_data[current_route] = {}
            
            # Detect Time Window header (e.g., "T_plus_1 (2026-09-02)")
            elif line.startswith("T_plus_"):
                # Extracts "T_plus_1"
                current_window = line.split()[0].strip()
                if current_route and current_window not in route_data[current_route]:
                    route_data[current_route][current_window] = []
            
            # Detect Price line (handles indentation automatically via strip)
            elif line.startswith("Price:") and current_route and current_window:
                try:
                    price_str = line.split("₹")[-1]
                    clean_price = int(price_str.replace(",", "").strip())
                    route_data[current_route][current_window].append(clean_price)
                except (IndexError, ValueError):
                    pass

    # Calculate Medians
    route_medians = {}
    for route, windows in route_data.items():
        route_medians[route] = {}
        for window, prices in windows.items():
            if prices:
                route_medians[route][window] = statistics.median(prices)

    return route_medians

# --- 3. Mathematical Model ---
def calculate_apix(base_prices, target_prices):
    """Calculates the Airfare Price Index (APIx) using the matched mathematical model."""
    route_level_indices = {}
    
    print("\n--- DETECTED DATA IN FILES ---")
    print(f"Base file routes found:   {list(base_prices.keys())}")
    print(f"Target file routes found: {list(target_prices.keys())}")
    
    print("\n--- PRICE RELATIVITY & ROUTE LEVEL INDEX (RLI) ---")
    
    total_active_route_weight = 0

    for route, route_weight in ROUTE_WEIGHTS.items():
        # Check if route exists in both parsed datasets
        if route not in base_prices:
            print(f"Skipping '{route}': Not found in Base Data text file.")
            continue
        if route not in target_prices:
            print(f"Skipping '{route}': Not found in Target Data text file.")
            continue
            
        rli_sum = 0
        total_window_weight = 0
        
        for window, win_weight in WINDOW_WEIGHTS.items():
            p_zero = base_prices[route].get(window)
            x = target_prices[route].get(window)
            
            if p_zero is not None and x is not None:
                price_relativity = (x / p_zero) * 100
                rli_sum += win_weight * price_relativity
                total_window_weight += win_weight
            else:
                print(f"  [Warning] Missing data for '{route}' at window '{window}'")
                
        # Normalize RLI if some windows were missing
        if total_window_weight > 0:
            normalized_rli = rli_sum / total_window_weight
            route_level_indices[route] = normalized_rli
            total_active_route_weight += route_weight
            print(f"-> {route} RLI: {normalized_rli:.4f}")
        else:
            print(f"-> {route} RLI: Could not calculate (no valid window pairs).")

    print("\n--- FINAL APIx CALCULATION ---")
    if not route_level_indices:
        print("Final Daily APIx: 0.00 (No routes could be evaluated)")
        return 0.0

    final_apix = 0
    for route, rli in route_level_indices.items():
        weight = ROUTE_WEIGHTS[route]
        final_apix += weight * rli

    # Normalize across active route weights if some routes were skipped
    if total_active_route_weight < 1.0 and total_active_route_weight > 0:
        final_apix = final_apix / total_active_route_weight

    print(f"Final Daily APIx: {final_apix:.2f}")
    
    price_change = final_apix - 100
    direction = "rose" if price_change > 0 else "fell"
    print(f"Significance: The overall price index {direction} by {abs(price_change):.2f}% relative to the base day.")
    
    return final_apix


# --- 4. Main Execution ---
if __name__ == "__main__":
    # Replace with your actual text file names/paths
    base_file = "C:\\Users\\shiva\\OneDrive\\Desktop\\CS\\base_day.txt"
    target_file = "C:\\Users\\shiva\\OneDrive\\Desktop\\CS\\target_day.txt"
    
    try:
        base_medians = parse_and_calculate_medians(base_file)
        target_medians = parse_and_calculate_medians(target_file)
        
        calculate_apix(base_medians, target_medians)
        
    except FileNotFoundError as e:
        print(f"Error: {e}")