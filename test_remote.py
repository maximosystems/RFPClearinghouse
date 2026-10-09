import asyncio
import json
from fastmcp import Client

async def test_dual_cam_pipeline():
    railway_url = "https://rfpclearinghouse-production.up.railway.app/sse"
    
    print(f"📡 Connecting to remote MCP server at {railway_url}...")
    
    try:
        async with Client(railway_url) as client:
            print("✅ Connection established successfully!\n")
            
            print("🔍 Firing 'get_all_nationwide_rfps' tool remotely (Nationwide Firehose)...")
            print("⏳ (Intercepting nationwide DemandStar and OpenGov nodes; scoring deep text...)")
            
            # Calls the dedicated nationwide tool without query constraints
            result = await client.call_tool(
                "get_all_nationwide_rfps",
                arguments={}
            )
            
            print("\n📦 RAW NATIONWIDE DUAL-CAM JSON RESPONSE FROM RAILWAY:")
            print("=" * 70)
            
            response_text = result.content[0].text
            parsed_json = json.loads(response_text)
            
            # Pretty-print the entire nationwide list ranked by friction_score
            print(json.dumps(parsed_json, indent=2))
            print("=" * 70)
            
            if isinstance(parsed_json, list):
                print(f"\n📊 Total Nationwide Bids Ingested & Scored: {len(parsed_json)}")
            
    except Exception as e:
        print(f"\n❌ Connection or execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_dual_cam_pipeline())
