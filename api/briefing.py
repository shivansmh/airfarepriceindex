import json
import os
import sys
from pathlib import Path



def generate_comprehensive_briefing(
    apix_json_path="dashboard/apix_output.json",
    target_data_json_path="dashboard/target_day.json",
    output_path="api/daily_briefing.json",
):
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if api_key:
        from google import genai
        client = genai.Client(api_key=api_key)
    else:
        client = None

    apix_path = Path(apix_json_path)
    target_path = Path(target_data_json_path)

    if apix_path.exists():
        apix_data = json.loads(apix_path.read_text(encoding="utf-8"))
    else:
        apix_data = {"error": f"APIx output data not found: {apix_path}"}

    if target_path.exists():
        target_raw_data = json.loads(target_path.read_text(encoding="utf-8"))
    else:
        target_raw_data = {"error": f"Target raw data not found: {target_path}"}

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
    2. Highlight which specific routes and advance booking windows drove this movement using the raw data details.
    3. Point out any notable price variances or anomalies discovered in the granular scrape data.
    4. Maintain a formal, objective institutional tone. Do not use markdown headers inside the briefing text—format as clean narrative paragraphs.
    5. If the supplied data supports a credible explanation, mention it cautiously; do not invent news, causes, or facts that are not present in the datasets.
    6. Conclude with a forward-looking statement on expected airfare trends and potential policy implications.
    """

    if client:
        print("Sending macro summary and full granular data to Gemini...")
        response = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=prompt,
        )
        briefing_text = (response.text or "").strip()
        if not briefing_text:
            raise RuntimeError("Gemini returned an empty briefing.")
    else:
        print("GEMINI_API_KEY is not configured; generating a local data-derived briefing.")
        daily = float(apix_data.get("daily_apix", apix_data.get("final_apix", 100)) or 100)
        change = float(apix_data.get("price_change_from_base_percent", apix_data.get("percentage_change", daily - 100)) or 0)
        direction = apix_data.get("direction", "rose" if change > 0 else "fell" if change < 0 else "was unchanged")
        route_indices = apix_data.get("route_level_apix", {})
        route_summary = ", ".join(f"{route} at {float(value):.2f}" for route, value in route_indices.items()) or "no route-level values available"
        briefing_text = "\n\n".join([
            f"The daily Airfare Price Index is {daily:.2f}, indicating that the monitored basket {direction} by {abs(change):.2f}% relative to its base level of 100.00.",
            f"The route-level readings are {route_summary}. These values identify the corridors contributing most directly to the composite movement.",
            "The refreshed report is based on the latest scraped target-day observations and the available advance-purchase windows. No additional causal interpretation is asserted without a configured external research source.",
            "This local data-derived briefing will be replaced automatically by the Gemini-generated narrative whenever GEMINI_API_KEY is configured for the repository workflow.",
        ])

    frontend_payload = {
        "timestamp": apix_data.get("timestamp", "Unknown"),
        "final_apix": apix_data.get("final_apix", 0),
        "percentage_change": apix_data.get("percentage_change", 0),
        "trend": apix_data.get("trend", "stable"),
        "briefing": briefing_text,
    }

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(frontend_payload, indent=4, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[Success] Comprehensive briefing generated and saved to {output}!")


if __name__ == "__main__":
    args = sys.argv[1:]
    generate_comprehensive_briefing(*args[:3])
