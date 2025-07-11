import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Read the data
data = pd.read_csv('parsed_distance_data.csv')

# Define wavelengths for each LED
LED_WAVELENGTHS = {
    "blue": 470,
    "green": 525,
    "red": 660,
    "ir": 940
}

# Add wavelength column to the data
data["Wavelength"] = data["LED"].map(LED_WAVELENGTHS)

# Group by wavelength and compute mean of IR and Red values
avg_response = data.groupby("Wavelength")[["Avg_IR", "Avg_Red"]].mean().reset_index()

# Normalize both Avg_IR and Avg_Red for QE-style comparison
avg_response["QE_IR"] = avg_response["Avg_IR"] / avg_response["Avg_IR"].max()
avg_response["QE_Red"] = avg_response["Avg_Red"] / avg_response["Avg_Red"].max()

# Plot QE vs wavelength
plt.figure(figsize=(10, 6))
sns.lineplot(x="Wavelength", y="QE_IR", data=avg_response, marker="o", label="IR Channel QE")
sns.lineplot(x="Wavelength", y="QE_Red", data=avg_response, marker="o", label="Red Channel QE")
plt.title("Relative Quantum Efficiency vs Wavelength")
plt.xlabel("Wavelength (nm)")
plt.ylabel("Normalized Quantum Efficiency")
plt.grid(True)
plt.legend()
plt.tight_layout()
plt.show()
