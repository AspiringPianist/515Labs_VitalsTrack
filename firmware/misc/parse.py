import re
import pandas as pd

# Reload input text after code state reset
with open("tmp.txt", "r", encoding="utf-8") as f:
    raw_text = f.read()

# Extract all lines matching BLE data pattern
pattern = r"📊 (\w+) @ (\d+)mm => IR: ([\d.]+), Red: ([\d.]+)"
matches = re.findall(pattern, raw_text)

# Convert matches to DataFrame
data = pd.DataFrame(matches, columns=["LED", "Distance_mm", "Avg_IR", "Avg_Red"])
data["Distance_mm"] = data["Distance_mm"].astype(int)
data["Avg_IR"] = data["Avg_IR"].astype(float)
data["Avg_Red"] = data["Avg_Red"].astype(float)

# Save CSV
csv_path = "parsed_distance_data.csv"
data.to_csv(csv_path, index=False)

csv_path
