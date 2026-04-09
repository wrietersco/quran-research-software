from pathlib import Path
p = Path("src/ui/question_refiner_tab.py")
t = p.read_text(encoding="utf-8")
assert "_find_verses_preview" in t
print("file ok, len", len(t))
