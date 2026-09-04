import argparse
import json
import os
from pathlib import Path
from google import genai


def generate_comprehensive_briefing(
    apix_json_path="apix_output.json",
    target_data_json_path="target_day.json",
    output_path="daily_briefing.json",
):
    """Generate the public dashboard briefing from the latest pipeline exports."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)

    def load_json(path, fallback):
        source = Path(path)
        if source.exists():
            with source.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        return fallback

    apix_data = load_json(apix_json_path, {"error": "APIx output data not found."})
    target_raw_data = load_json(target_data_json_path, {"error": "Target raw data not found."})

    prompt = f"""
You are the Chief Economist and Senior Data Analyst for the Reserve Bank of India (RBI) and MoSPI.

I am providing you with two distinct datasets from our airfare intelligence pipeline:

--- DATASET 1: MACRO INDEX SUMMARY (APIx & RLI) ---
{json.dumps(apix_data, indent=2)}

--- DATASET 2: FULL GRANULAR TARGET DAY SCRAPED DATA ---
{json.dumps(target_raw_data, indent=2)}

--- TASK ---
Analyze both datasets thoroughly. Write a professional, data-driven 4-paragraph daily executive briefing for RBI policy makers.
1. Summarize the headline Airfare Price Index (APIx) movement and overall market trend.
2. Highlight which specific routes and advance booking windows (e.g., T+1 vs T+30) drove this movement using the raw data details.
3. Point out any notable price variances or anomalies discovered in the granular scrape data.
4. Maintain a formal, objective institutional tone. Do not use markdown headers inside the briefing text—format as clean narrative paragraphs.
"""

    print("Sending macro summary and full granular data to Gemini...")
    response = client.models.generate_content(
        model="gemini-3.6-flash",
        contents=prompt,
    )
    briefing_text = (response.text or "").strip()

    frontend_payload = {
        "timestamp": apix_data.get("timestamp", apix_data.get("generated_at", "Unknown")),
        "final_apix": apix_data.get("final_apix", apix_data.get("apix", 0)),
        "percentage_change": apix_data.get("percentage_change", apix_data.get("price_change_from_base_percent", 0)),
        "trend": apix_data.get("trend", apix_data.get("direction", "stable")),
        "briefing": briefing_text,
    }

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as handle:
        json.dump(frontend_payload, handle, indent=2, ensure_ascii=False)

    print(f"[Success] Comprehensive briefing generated and saved to {destination}!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate the dashboard daily briefing")
    parser.add_argument("apix_json_path", nargs="?", default="apix_output.json")
    parser.add_argument("target_data_json_path", nargs="?", default="target_day.json")
    parser.add_argument("output_path", nargs="?", default="daily_briefing.json")
    args = parser.parse_args()
    generate_comprehensive_briefing(
        apix_json_path=args.apix_json_path,
        target_data_json_path=args.target_data_json_path,
        output_path=args.output_path,
    )
