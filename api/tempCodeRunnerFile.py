import google-genai
import json
import os

def generate_daily_briefing(apix_json_path="apix_output.json", output_path="daily_briefing.json"):
    # 1. Configure your API Key (Store this in your environment variables, NOT in the code)
    # For Windows: setx GEMINI_API_KEY "your_api_key_here"
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
    
    # 2. Load the calculated APIx data
    with open(apix_json_path, 'r', encoding='utf-8') as f:
        apix_data = json.load(f)
        
    # 3. Create a strict system prompt for the AI
    prompt = f"""
    You are the Chief Economist for the Reserve Bank of India (RBI). 
    I will provide you with today's Airfare Price Index (APIx) data.
    
    Data:
    - Current APIx: {apix_data['final_apix']}
    - Percentage Change: {apix_data['percentage_change']}% ({apix_data['trend']})
    - Route Level Data: {json.dumps(apix_data['route_level_indices'])}
    
    Task: Write a concise, professional 3-sentence daily executive briefing based strictly on this data. 
    Do not hallucinate external events. Point out which route drove the inflation/deflation the most.
    Format as plain text without markdown.
    """
    
    print("Calling Gemini API for Executive Briefing...")
    
    # 4. Generate the response using Gemini 1.5 Flash (Fastest & cheapest for this)
    model = genai.GenerativeModel('gemini-1.5-flash')
    response = model.generate_content(prompt)
    
    briefing_text = response.text.strip()
    
    # 5. Save the briefing to a new JSON file for the frontend to consume
    frontend_payload = {
        "date": apix_data['timestamp'],
        "briefing": briefing_text
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(frontend_payload, f, indent=4)
        
    print(f"Briefing saved to {output_path}: \n{briefing_text}")

# Run this after calculate_and_save_apix()
# generate_daily_briefing()