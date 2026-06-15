import json
from pathlib import Path
q = Path("C:/Users/user/Documents/gourmet-sns/queue")
for f in sorted(q.glob("*_instagram.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        print(f"{f.name}: platform={d.get('platform')} status={d.get('status')}")
    except Exception as e:
        print(f"{f.name}: PARSE ERROR {e}")
