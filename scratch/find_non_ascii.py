with open("frontend/src/App.jsx", "r", encoding="utf-8") as f:
    lines = f.readlines()

for idx, line in enumerate(lines):
    for char in line:
        code = ord(char)
        if code > 127 and char not in ['₹', '—', '═', '─', '’', 'é', '📊', '🛡️']:
            # Avoid printing unicode character directly to stdout to prevent windows shell crash
            print(f"Line {idx+1}: char code {code}")
            break
