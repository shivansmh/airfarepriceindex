import json
import os
from google import genai

def generate_comprehensive_briefing(
    apix_json_path="apix_output.json", 
    target_data_json_path="target_day_data.json", 
    output_path="daily_briefing.json"
):
    # Initialize client with your API key
    client = genai.Client(api_key="AQ.Ab8RN6Ii3hwnKusEQ-hQSjVGH0Z8rlGp7Mubi0rkKUnpKYyzKw")
    
    # 1. Load the Final APIx & RLI calculated JSON
    if os.path.exists(apix_json_path):
        with open(apix_json_path, 'r', encoding='utf-8') as f:
            apix_data = json.load(f)
    else:
        apix_data = {"error": "APIx output data not found."}

    # 2. Load the Full Target Day Scraped Data JSON
    if os.path.exists(target_data_json_path):
        with open(target_data_json_path, 'r', encoding='utf-8') as f:
            target_raw_data = json.load(f)
    else:
        target_raw_data = {"error": "Target raw data not found."}

    # 3. Construct prompt combining both datasets
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
    5. Search for news article from trusted sources to explain the cause of inflations on specific routes and an all round aviation news of the country on the specific routes. Provide a brief summary of the news article in the briefing.
    6. Conclude with a forward-looking statement on expected airfare trends and potential policy implications
    """
    
    print("Sending macro summary and full granular data to Gemini...")
    
    # 4. Use gemini-3.6-flash as requested by the API error message
    response = client.models.generate_content(
        model='gemini-3.6-flash',
        contents=prompt,
    )
    
    briefing_text = response.text.strip()
    
    # 5. Package payload for GitHub Pages frontend
    frontend_payload = {
        "timestamp": apix_data.get('timestamp', 'Unknown'),
        "final_apix": apix_data.get('final_apix', 0),
        "percentage_change": apix_data.get('percentage_change', 0),
        "trend": apix_data.get('trend', 'stable'),
        "briefing": briefing_text
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(frontend_payload, f, indent=4, ensure_ascii=False)
        
    print(f"[Success] Comprehensive briefing generated and saved to {output_path}!")

if __name__ == "__main__":
    generate_comprehensive_briefing()