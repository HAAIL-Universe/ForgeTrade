"""Quick debug: check RL fields in /strategy/insight API response."""
import httpx
import json

r = httpx.get("http://localhost:8080/strategy/insight")
d = r.json()
ins = d.get("insights", {})
print(f"{len(ins)} streams")
for name, data in ins.items():
    rl_fields = {k: v for k, v in data.items() if "rl" in k}
    print(f"  {name}: {rl_fields}")
