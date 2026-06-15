import json
from pathlib import Path
q = Path("C:/Users/user/Documents/gourmet-sns/queue")
for f in sorted(q.glob("*_instagram.json")):
    try:
        d = json.loads(f.read_text(encoding="utf-8-sig"))
        d["status"] = "approved"
        d.pop("error", None)
        f.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Fixed: {f.name}")
    except Exception as e:
        print(f"ERROR {f.name}: {e}")
