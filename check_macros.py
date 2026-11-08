from backend.bridge import Bridge
from backend.config import Config
c = Config()
b = Bridge(c)
ms = b.list_macros()
print("=== 已保存宏数量：", len(ms))
for m in ms:
    print(f"  - {m['name']}: {len(m['steps'])} 步")
    for i, s in enumerate(m["steps"]):
        t = s.get("type", "")
        if t == "type":
            v = s.get("value", "")[:30]
            print(f"      {i+1}. type: {v}")
        elif t == "press":
            print(f"      {i+1}. press: {s.get('press_name', '')}")
        else:
            note = s.get("note", "")[:30]
            print(f"      {i+1}. {t}: {note}")
