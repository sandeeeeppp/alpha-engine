"""
Phase 5 Gate Test — Alpha Engine SSE Stream Validator (Hub-and-Spoke Edition)
Validates the full event sequence including agent_status events.
"""
import json
import requests

url = "http://localhost:8000/api/analyze"
payload = {"query": "Analyse NVDA volatility for FY2025"}

print("=" * 65)
print("  Alpha Engine  --  Phase 5 Gate Test (Hub-and-Spoke)")
print("=" * 65)
print(f"  POST {url}")
print(f"  Payload: {json.dumps(payload)}")
print("-" * 65)

seen_events = set()

try:
    with requests.post(url, json=payload, stream=True, timeout=120) as response:
        response.raise_for_status()
        current_event_type = None

        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8")

            if line.startswith("event:"):
                current_event_type = line.split(":", 1)[1].strip()
                continue

            if line.startswith("data:"):
                data_str = line.split(":", 1)[1].strip()
                seen_events.add(current_event_type)

                if current_event_type == "agent_status":
                    data = json.loads(data_str)
                    print(f"  [{data['node'].upper():>12}] {data['message']}")

                elif current_event_type == "agent_action":
                    data = json.loads(data_str)
                    if data.get("type") == "tool_start":
                        print(f"  {'':>12}   >> tool_start: {data['tool']}({json.dumps(data.get('input', {}))})")
                    elif data.get("type") == "tool_end":
                        preview = data.get("output_preview", "")[:120]
                        print(f"  {'':>12}   << tool_end:   {data['tool']} -> {preview}...")

                elif current_event_type == "agent_token":
                    data = json.loads(data_str)
                    print(data.get("content", ""), end="", flush=True)

                elif current_event_type == "alpha_signal":
                    data = json.loads(data_str)
                    print(f"\n\n  [ALPHA SIGNAL]")
                    print(f"  {json.dumps(data, indent=4)}")

                elif current_event_type == "error":
                    data = json.loads(data_str)
                    print(f"\n  [ERROR] {data.get('detail')}")

                elif current_event_type == "done":
                    print(f"\n  [DONE] Stream terminated cleanly.")

                current_event_type = None

except requests.exceptions.ConnectionError:
    print("  [ERROR] Connection refused. Is the server running?")
except Exception as e:
    print(f"\n  [ERROR] {e}")

# ── Phase 5 Gate Assertion ────────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  Phase 5 Gate Checklist:")
required = ["agent_status", "agent_action", "agent_token", "alpha_signal", "done"]
all_pass = True
for evt in required:
    ok = evt in seen_events
    if not ok:
        all_pass = False
    print(f"    {'PASS' if ok else 'FAIL'}  {evt}")

print("-" * 65)
print(f"  PHASE 5 GATE: {'PASSED' if all_pass else 'FAILED'}")
print("=" * 65)