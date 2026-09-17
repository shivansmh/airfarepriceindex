import statistics

def extract_window_medians(filepath):
    window_prices = {}
    current_window = None

    # Use utf-8 encoding to properly handle the ₹ symbol
    with open(filepath, 'r', encoding='utf-8') as file:
        for line in file:
            line = line.strip()
            
            # Detect the time window header (e.g., "T_plus_1 (2026-09-02)")
            if line.startswith("T_plus_"):
                # Isolate just the "T_plus_X" part to use as our variable key
                current_window = line.split()[0]
                window_prices[current_window] = []
            
            # Detect the price line and assign it to the current window
            elif line.startswith("Price:") and current_window:
                # Remove "Price:", whitespace, the Rupee symbol, and commas
                raw_price = line.replace("Price:", "").replace("₹", "").replace(",", "").strip()
                
                if raw_price.isdigit():
                    window_prices[current_window].append(int(raw_price))

    # Calculate the median for each time window
    medians = {}
    for window, prices in window_prices.items():
        if prices:
            medians[window] = statistics.median(prices)
            
    return medians

# --- How to use it ---
# Replace 'flight_data.txt' with the actual name of your file
time_window_medians = extract_window_medians('flight_report.txt')

# Print the final dictionary
print("Median Prices Extracted:")
for window, median_price in time_window_medians.items():
    print(f"{window}: ₹{median_price}")

# You can now access specific windows like variables:
# t1_median = time_window_medians.get('T_plus_1')