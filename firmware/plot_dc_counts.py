import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import UnivariateSpline
from collections import defaultdict

# === Raw Data from test_distance.py ===
distances = [0]*26 + [0]*25 + [5]*26 + [10]*25 + [15]*25 + [20]*25

ir_values = [
    31.10, 30.55, 30.97, 31.17, 31.30, 32.57, 37.44, 43.65, 53.48, 63.25,
    86.29, 138.00, 299.72, 861.19, 2533.77, 5667.65, 9189.26, 12319.58,
    15120.39, 17641.12, 19921.78, 21995.11, 23888.15, 25623.43, 27219.90,
    28693.55,
    *[65535.0]*25,
    *[65535.0]*26,
    17090.20, 17152.85, 17212.90, 17259.03, 17280.02, 17293.07, 17296.70,
    17275.99, 17259.33, 17247.81, 17224.36, 17201.36, 17197.60, 17194.40,
    17172.27, 17138.82, 17110.17, 17084.21, 17072.30, 17068.24, 17070.02,
    17073.49, 17082.24, 17087.94, 17095.98, 17099.52,
    8020.90, 8000.80, 8000.80, 7986.23, 7978.78, 7983.63, 7991.74, 8002.20,
    8012.50, 8019.09, 8027.52, 8037.39, 8047.17, 8053.11, 8057.61, 8061.19,
    8061.68, 8061.92, 8060.87, 8055.43, 8048.97, 8045.95, 8045.99, 8046.81,
    8047.71, 8050.80,
    4941.70, 4989.50, 5013.73, 5042.48, 5073.70, 5101.97, 5124.31, 5145.70,
    5164.56, 5181.27, 5195.73, 5206.72, 5213.07, 5216.87, 5220.27, 5225.36,
    5233.71, 5241.61, 5249.78, 5263.92, 5278.93, 5293.17, 5301.98, 5306.38,
    5311.73, 5315.83
]

red_values = [
    12.10, 12.25, 12.47, 12.38, 12.46, 15.87, 26.86, 40.88, 58.09, 69.64,
    74.31, 134.62, 456.92, 1140.98, 2923.81, 6319.66, 9765.02, 12361.87,
    14648.39, 16951.92, 19192.12, 21298.62, 23221.94, 24941.37, 26341.32,
    27669.00,
    *[61491.05 + i for i in range(25)],
    *[65535.0]*26,
    17546.30, 17597.25, 17639.73, 17672.15, 17696.62, 17715.23, 17720.37,
    17704.38, 17692.76, 17685.29, 17669.55, 17654.75, 17653.73, 17654.50,
    17639.96, 17616.51, 17594.37, 17571.91, 17563.53, 17563.12, 17568.42,
    17576.40, 17589.51, 17598.56, 17609.34, 17618.32,
    7569.30, 7559.95, 7563.77, 7551.33, 7546.08, 7552.47, 7562.39, 7574.33,
    7585.64, 7594.23, 7603.47, 7612.36, 7620.92, 7625.63, 7628.63, 7630.72,
    7630.68, 7630.65, 7629.67, 7623.99, 7617.12, 7613.59, 7612.38, 7611.96,
    7612.00, 7613.83,
    4251.80, 4288.30, 4305.77, 4326.17, 4351.26, 4374.37, 4391.51, 4407.56,
    4421.94, 4434.85, 4446.10, 4455.49, 4461.78, 4465.89, 4469.43, 4473.81,
    4480.11, 4485.80, 4491.74, 4502.14, 4513.03, 4523.45, 4530.53, 4535.13,
    4540.47, 4545.03
]

# === Group by distance and average ===
ir_by_dist = defaultdict(list)
red_by_dist = defaultdict(list)

for d, ir, red in zip(distances, ir_values, red_values):
    ir_by_dist[d].append(ir)
    red_by_dist[d].append(red)

unique_d = sorted(ir_by_dist.keys())
ir_avg = [np.mean(ir_by_dist[d]) for d in unique_d]
red_avg = [np.mean(red_by_dist[d]) for d in unique_d]

# === Better interpolation using UnivariateSpline ===
x_smooth = np.linspace(min(unique_d), max(unique_d), 500)
smoothing_factor = len(unique_d) * 100

ir_spline = UnivariateSpline(unique_d, ir_avg, s=smoothing_factor, k=3)
red_spline = UnivariateSpline(unique_d, red_avg, s=smoothing_factor, k=3)

ir_smooth = ir_spline(x_smooth)
red_smooth = red_spline(x_smooth)

# Main plot
plt.plot(x_smooth, ir_smooth, label='IR (Smoothed)', color='blue', linewidth=2)
plt.plot(x_smooth, red_smooth, label='Red (Smoothed)', color='red', linewidth=2)
plt.scatter(unique_d, ir_avg, color='navy', s=50, alpha=0.7, zorder=5, label='IR Data Points')
plt.scatter(unique_d, red_avg, color='darkred', s=50, alpha=0.7, zorder=5, label='Red Data Points')
plt.title("Improved DC Response vs Distance (MAX30100)")
plt.xlabel("Distance (mm)")
plt.ylabel("Average Sensor Reading")
plt.grid(True, alpha=0.3)
plt.legend()

# Residuals plot
# plt.subplot(2, 1, 2)
# ir_residuals = np.array(ir_avg) - ir_spline(unique_d)
# red_residuals = np.array(red_avg) - red_spline(unique_d)

# plt.scatter(unique_d, ir_residuals, color='blue', s=50, alpha=0.7, label='IR Residuals')
# plt.scatter(unique_d, red_residuals, color='red', s=50, alpha=0.7, label='Red Residuals')
# plt.axhline(y=0, color='black', linestyle='--', alpha=0.5)
# plt.title("Interpolation Residuals (Data - Fit)")
# plt.xlabel("Distance (mm)")
# plt.ylabel("Residual")
# plt.grid(True, alpha=0.3)
# plt.legend()

# plt.tight_layout()
plt.show()

# Print some statistics
# print("Interpolation Quality:")
# print(f"IR RMSE: {np.sqrt(np.mean(ir_residuals**2)):.2f}")
# print(f"Red RMSE: {np.sqrt(np.mean(red_residuals**2)):.2f}")
print(f"Number of data points used: {len(unique_d)}")
print(f"Smoothing factor: {smoothing_factor}")