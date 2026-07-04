with open("frontend/src/App.jsx", "r", encoding="utf-8") as f:
    content = f.read()

import re

# Find streamlit pattern
st_matches = re.findall(r"\bst\.\w+", content)
if st_matches:
    print("Found Streamlit calls:", set(st_matches))

# Find undefined functions
helpers = ["fmt_inr", "fmt_pct", "now_ist", "is_market_open", "is_after_squareoff"]
for h in helpers:
    if h in content:
        print(f"Found helper: {h}")
