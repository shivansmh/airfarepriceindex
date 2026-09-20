from __future__ import annotations
import json, re, sys
from pathlib import Path
import openpyxl

INPUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('config/finalroutes.xlsx')
OUTPUT = Path('config/routes.json')
CODES = {
 'ADAMPUR':'AIP','AGARTALA':'IXA','AGATTI ISLAND':'AGX','AHMEDABAD':'AMD','AIZAWL':'AJL','AMRITSAR':'ATQ','AURANGABAD':'IXU','Ayodhya International Airp':'AYJ','BELGAUM':'IXG','BENGALURU':'BLR','BHATINDA':'BUP','BHAVNAGAR':'BHU','BHOPAL':'BHO','BHUBANESWAR':'BBI','BHUJ':'BHJ','BIKANER':'BKB','BILASPUR':'PAB','CHANDIGARH':'IXC','CHENNAI':'MAA','COIMBATORE':'CJB','Cuddapah':'CDP','DABOLIM':'GOI','DARBHANGA':'DBR','DELHI':'DEL','DHARAMSALA':'DHM','DIBRUGARH':'DIB','DIMAPUR':'DMU','DIU':'DIU','Deoghar':'DGH','GAYA':'GAY','GUWAHATI':'GAU','GWALIOR':'GWL','Goa':'GOI','Gondia':'GDB','HINDON AIRPORT':'HDO','HUBLI':'HBX','HYDERABAD':'HYD','IMPHAL':'IMF','INDORE':'IDR','Itanagar':'HGI','JABALPUR':'JLR','JAGDALPUR':'JGB','JAIPUR':'JAI','JAISALMER':'JSA','JALGAON':'JLG','JAMMU':'IXJ','JAMNAGAR':'JGA','JAMSHEDPUR':'IXW','JEYPORE':'PYB','JHARSUGUDA':'VEJ','JODHPUR':'JDH','JORHAT':'JRH','KALABURAGI':'GBI','KANDLA':'IXY','KANNUR':'CNN','KESHOD':'IXK','KHAJURAHO':'HJR','KOCHI':'COK','KOLHAPUR':'KLH','KOLKATA':'CCU','KOZHIKODE':'CCJ','KURNOOL':'KJB','Kishangarh':'KQH','LEH':'IXL','LILABARI':'IXI','LUCKNOW':'LKO','LUDHIANA':'LUH','MADURAI':'IXM','MANGALORE':'IXE','MUMBAI':'BOM','Malvan':'SDW','NAGPUR':'NAG','NANDED':'NDC','NASIK':'ISK','PASIGHAT':'IXT','PATNA':'PAT','PORT BLAIR':'IXZ','PUNE':'PNQ','RAIPUR':'RPR','RANCHI':'IXR','Rajkot International Airport':'HSR','SHILLONG':'SHL','SHIRDI':'SAG','SILCHAR':'IXS','SIMLA':'SLV','SRINAGAR':'SXR','SURAT':'STV','Shivamogga Airport':'RQY','TEZPUR':'TEZ','TEZU':'TEI','TIRUPATI':'TIR','TRIVANDRUM':'TRV','UDAIPUR':'UDR','VADODARA':'BDQ','VARANASI':'VNS','VIJAYAWADA':'VGA','VISAKHAPATNAM':'VTZ'
}

def clean(v): return str(v).strip()
wb=openpyxl.load_workbook(INPUT, read_only=True, data_only=True)
ws=wb['Directional Routes']
routes=[]
for state, origin, destination, passengers, contribution in ws.iter_rows(min_row=2, values_only=True):
    if not origin or not destination or clean(destination).upper() == 'STATE TOTAL': continue
    origin, destination, state = clean(origin), clean(destination), clean(state)
    if origin not in CODES or destination not in CODES: raise ValueError(f'Unmapped airport: {origin} or {destination}')
    routes.append({'state':state,'origin':origin,'origin_code':CODES[origin],'destination':destination,'destination_code':CODES[destination],'passengers':passengers,'contribution':contribution})
OUTPUT.write_text(json.dumps({'source_workbook':'finalroutes.xlsx','route_count':len(routes),'routes':routes}, indent=2, ensure_ascii=False)+'\n')
print(f'Wrote {len(routes)} routes across {len({r["state"] for r in routes})} states to {OUTPUT}')
