
#ifndef SENSOR_QUALITY_MODEL_H
#define SENSOR_QUALITY_MODEL_H

// Lightweight Sensor Quality Assessment Model
// Generated automatically - DO NOT EDIT MANUALLY

#define NUM_FEATURES 6
#define SCALE_FACTOR 1000

// Feature indices
enum FeatureIndex {
    FEATURE_HEARTRATE = 0,
    FEATURE_SPO2 = 1,
    FEATURE_ACCEL_MAG = 2,
    FEATURE_HR_CHANGE = 3,
    FEATURE_SPO2_CHANGE = 4,
    FEATURE_ACCEL_CHANGE = 5,
};

// Quantized model coefficients (scaled by 1000)
const int16_t model_coefficients[NUM_FEATURES] = {
    2759, // HeartRate
    3931, // SpO2
    169, // Accel_Mag
    -1874, // HR_Change
    -2038, // SpO2_Change
    -4785 // Accel_Change
};

// Quantized model intercept
const int16_t model_intercept = 2335;

// Quantized scaler mean values
const int16_t scaler_mean[NUM_FEATURES] = {
    -1251, // HeartRate
    27550, // SpO2
    992, // Accel_Mag
    2451, // HR_Change
    863, // SpO2_Change
    51 // Accel_Change
};

// Quantized scaler scale values
const int16_t scaler_scale[NUM_FEATURES] = {
    11711, // HeartRate
    17091, // SpO2
    111, // Accel_Mag
    5410, // HR_Change
    8871, // SpO2_Change
    127 // Accel_Change
};


// Fast integer-based quality prediction
// Returns: 1 for good quality, 0 for poor quality
inline int predict_quality(float features[NUM_FEATURES]) {
    int32_t score = model_intercept;
    
    for (int i = 0; i < NUM_FEATURES; i++) {
        // Scale the feature: (feature - mean) / scale
        int32_t scaled_feature = ((int32_t)(features[i] * SCALE_FACTOR) - scaler_mean[i]) * SCALE_FACTOR / scaler_scale[i];
        score += (scaled_feature * model_coefficients[i]) / SCALE_FACTOR;
    }
    
    // Apply sigmoid approximation: if score > 0, predict 1, else 0
    return (score > 0) ? 1 : 0;
}

// Quality assessment with feature extraction
inline int assess_sensor_quality(float hr, float spo2, float ax, float ay, float az,
                                float hr_prev, float spo2_prev, float accel_prev) {
    float features[NUM_FEATURES];
    
    // Calculate features
    float accel_mag = sqrt(ax*ax + ay*ay + az*az);
    
    features[FEATURE_HEARTRATE] = hr;
    features[FEATURE_SPO2] = spo2;
    features[FEATURE_ACCEL_MAG] = accel_mag;
    features[FEATURE_HR_CHANGE] = abs(hr - hr_prev);
    features[FEATURE_SPO2_CHANGE] = abs(spo2 - spo2_prev);
    features[FEATURE_ACCEL_CHANGE] = abs(accel_mag - accel_prev);
    
    return predict_quality(features);
}

#endif // SENSOR_QUALITY_MODEL_H
