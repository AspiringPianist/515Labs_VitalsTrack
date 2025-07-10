import pandas as pd
import matplotlib.pyplot as plt

# === LED Wavelength Mapping ===
LED_WAVELENGTHS = {
    "blue": 470,
    "green": 525,
    "red": 660,
    "ir": 940
}

# === File Paths ===
INPUT_CSV = "parsed_distance_data.csv"  # replace with actual file
RESULTS_FILENAME = "qe_results_from_csv.csv"

# === Load and Process CSV ===
df = pd.read_csv(INPUT_CSV)

# Group by LED and distance, take mean values
df_grouped = df.groupby(['Distance_mm', 'LED']).mean(numeric_only=True).reset_index()

# Pivot to get curves
pivot_ir = df_grouped.pivot(index='Distance_mm', columns='LED', values='Avg_IR')
pivot_red = df_grouped.pivot(index='Distance_mm', columns='LED', values='Avg_Red')

# Normalize using min-max scaling
norm_ir = (pivot_ir - pivot_ir.min()) / (pivot_ir.max() - pivot_ir.min())
norm_red = (pivot_red - pivot_red.min()) / (pivot_red.max() - pivot_red.min())

# Calculate Area Under Curve (AUC)
auc_ir = norm_ir.sum()
auc_red = norm_red.sum()

# Compute Relative QE ratios
rel_qe_ir = auc_ir / auc_ir['ir']
rel_qe_red = auc_ir / auc_ir['red']

# Save final results
result_df = pd.DataFrame({
    'LED': rel_qe_ir.index,
    'Wavelength_nm': [LED_WAVELENGTHS[led] for led in rel_qe_ir.index],
    'Relative_QE_vs_IR': rel_qe_ir.values,
    'Relative_QE_vs_Red': rel_qe_red.values
})
result_df.sort_values(by='Wavelength_nm', inplace=True)
result_df.to_csv(RESULTS_FILENAME, index=False)

print("\n✅ Results saved to", RESULTS_FILENAME)
print(result_df)

# Plot QE vs Wavelength
plt.figure(figsize=(10, 6))
plt.plot(result_df['Wavelength_nm'], result_df['Relative_QE_vs_IR'], 'r-o', label='QE vs IR')
plt.plot(result_df['Wavelength_nm'], result_df['Relative_QE_vs_Red'], 'b-o', label='QE vs Red')
plt.xlabel("Wavelength (nm)")
plt.ylabel("Relative QE")
plt.title("Quantum Efficiency vs Wavelength")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.savefig("qe_vs_wavelength_from_csv.png")
plt.show()
