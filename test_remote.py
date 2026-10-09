import asyncio
import json
from fastmcp import Client

async def test_dual_cam_pipeline():
    # Updated with your exact Railway Public URL
    railway_url = "https://rfpclearinghouse-production.up.railway.app/sse"
    
    print(f"📡 Connecting to remote MCP server at {railway_url}...")
    
    try:
        # FastMCP's Client natively negotiates the SSE connection over the internet
        async with Client(railway_url) as client:
            print("✅ Connection established successfully!\n")
            
            print("🔍 Firing 'run_friction_audit' tool remotely for 'Florida'...")
            print("⏳ (This may take 10-15 seconds as it intercepts live DemandStar and OpenGov nodes)")
            
            # This triggers the exact pipeline we just built:
            # RFP Ingestion -> Friction Scoring -> Suspected Incumbent Extraction
            result = await client.call_tool(
                "run_friction_audit",
                arguments={
                    "agency_keyword": "Florida" 
                }
            )
            
            print("\n📦 RAW DUAL-CAM JSON RESPONSE FROM RAILWAY:")
            print("=" * 70)
            
            # The result returns as a list of content blocks; we print the text of the first one
            response_text = result.content[0].text
            parsed_json = json.loads(response_text)
            
            # Pretty-print the results so you can see the ai_next_action_prompt
            print(json.dumps(parsed_json, indent=2))
            print("=" * 70)
            
    except Exception as e:
        print(f"\n❌ Connection or execution failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_dual_cam_pipeline())
