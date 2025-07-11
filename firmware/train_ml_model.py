import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, accuracy_score
import joblib
import struct

class LightweightQualityTrainer:
    def __init__(self, csv_file='oximeter_data.csv'):
        self.csv_file = csv_file
        self.df = None
        self.scaler = StandardScaler()
        self.model = None
        self.feature_names = []
        
    def load_and_preprocess_data(self):
        """Load and preprocess oximeter data"""
        print("📊 Loading oximeter data...")
        self.df = pd.read_csv(self.csv_file)
        
        # Convert timestamp
        self.df['Timestamp'] = pd.to_datetime(self.df['Timestamp'])
        
        # Calculate time differences
        self.df['TimeDiff'] = self.df['Timestamp'].diff().dt.total_seconds()
        
        print(f"✅ Loaded {len(self.df)} samples")
        
    def engineer_lightweight_features(self):
        """Engineer minimal but effective features"""
        print("🔧 Engineering lightweight features...")
        
        # Simple rolling statistics (window=3 for minimal memory)
        window = 3
        
        # Heart Rate Features
        self.df['HR_Prev'] = self.df['HeartRate'].shift(1)
        self.df['HR_Change'] = np.abs(self.df['HeartRate'] - self.df['HR_Prev'])
        self.df['HR_Mean3'] = self.df['HeartRate'].rolling(window).mean()
        self.df['HR_Std3'] = self.df['HeartRate'].rolling(window).std()
        
        # SpO2 Features  
        self.df['SpO2_Prev'] = self.df['SpO2'].shift(1)
        self.df['SpO2_Change'] = np.abs(self.df['SpO2'] - self.df['SpO2_Prev'])
        
        # Accelerometer Features
        self.df['Accel_Mag'] = np.sqrt(self.df['Ax']**2 + self.df['Ay']**2 + self.df['Az']**2)
        self.df['Accel_Prev'] = self.df['Accel_Mag'].shift(1)
        self.df['Accel_Change'] = np.abs(self.df['Accel_Mag'] - self.df['Accel_Prev'])
        
        # Drop NaN values
        self.df = self.df.dropna()
        
        print(f"✅ Features engineered. {len(self.df)} samples remaining.")
        
    def create_quality_labels(self):
        """Create quality labels with simple thresholds"""
        print("🏷️ Creating quality labels...")
        
        # Define thresholds for dirty data
        dirty_conditions = (
            (self.df['HR_Change'] > 15) |  # Sudden HR changes > 15 BPM
            (self.df['SpO2_Change'] > 3) |  # Sudden SpO2 changes > 3%
            (self.df['HeartRate'] < 40) | (self.df['HeartRate'] > 180) |  # Implausible HR
            (self.df['SpO2'] < 80) | (self.df['SpO2'] > 100) |  # Implausible SpO2
            (self.df['Accel_Change'] > 0.2)  # High motion
        )
        
        self.df['Quality_Label'] = (~dirty_conditions).astype(int)
        
        good_samples = self.df['Quality_Label'].sum()
        dirty_samples = len(self.df) - good_samples
        
        print(f"📊 Quality Distribution:")
        print(f"   Good samples: {good_samples} ({good_samples/len(self.df)*100:.1f}%)")
        print(f"   Dirty samples: {dirty_samples} ({dirty_samples/len(self.df)*100:.1f}%)")
        
    def train_lightweight_model(self):
        """Train a lightweight logistic regression model"""
        print("🤖 Training lightweight model...")
        
        # Select minimal feature set
        self.feature_names = [
            'HeartRate', 'SpO2', 'Accel_Mag',
            'HR_Change', 'SpO2_Change', 'Accel_Change'
        ]
        
        X = self.df[self.feature_names].fillna(0)
        y = self.df['Quality_Label']
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=42, stratify=y
        )
        
        # Scale features
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Train Logistic Regression (lightweight and interpretable)
        self.model = LogisticRegression(
            random_state=42, 
            class_weight='balanced',
            max_iter=1000
        )
        self.model.fit(X_train_scaled, y_train)
        
        # Evaluate
        y_pred = self.model.predict(X_test_scaled)
        accuracy = accuracy_score(y_test, y_pred)
        
        print(f"✅ Model Accuracy: {accuracy:.3f}")
        print("\n📊 Classification Report:")
        print(classification_report(y_test, y_pred))
        
        # Print model parameters for inspection
        print(f"\n🔍 Model Parameters:")
        print(f"   Coefficients: {self.model.coef_[0]}")
        print(f"   Intercept: {self.model.intercept_[0]}")
        print(f"   Scaler Mean: {self.scaler.mean_}")
        print(f"   Scaler Scale: {self.scaler.scale_}")
        
        return accuracy
    
    def quantize_model_parameters(self):
        """Quantize model parameters to int16 for ESP32"""
        print("⚡ Quantizing model parameters...")
        
        # Scale factor for quantization (use 1000 for good precision)
        scale_factor = 1000
        
        # Quantize coefficients
        coef_quantized = (self.model.coef_[0] * scale_factor).astype(np.int16)
        intercept_quantized = int(self.model.intercept_[0] * scale_factor)
        
        # Quantize scaler parameters
        mean_quantized = (self.scaler.mean_ * scale_factor).astype(np.int16)
        scale_quantized = (self.scaler.scale_ * scale_factor).astype(np.int16)
        
        print(f"✅ Quantization complete with scale factor: {scale_factor}")
        
        return {
            'coef': coef_quantized,
            'intercept': intercept_quantized,
            'mean': mean_quantized,
            'scale': scale_quantized,
            'scale_factor': scale_factor,
            'feature_names': self.feature_names
        }
    
    def generate_header_file(self, quantized_params):
        """Generate C header file for ESP32"""
        print("📝 Generating C header file...")
        
        header_content = f"""
#ifndef SENSOR_QUALITY_MODEL_H
#define SENSOR_QUALITY_MODEL_H

// Lightweight Sensor Quality Assessment Model
// Generated automatically - DO NOT EDIT MANUALLY

#define NUM_FEATURES {len(self.feature_names)}
#define SCALE_FACTOR {quantized_params['scale_factor']}

// Feature indices
enum FeatureIndex {{
"""
        
        for i, feature in enumerate(self.feature_names):
            header_content += f"    FEATURE_{feature.upper().replace(' ', '_')} = {i},\n"
        
        header_content += "};\n\n"
        
        # Add quantized parameters
        header_content += f"// Quantized model coefficients (scaled by {quantized_params['scale_factor']})\n"
        header_content += "const int16_t model_coefficients[NUM_FEATURES] = {\n"
        for i, coef in enumerate(quantized_params['coef']):
            header_content += f"    {coef}{',' if i < len(quantized_params['coef'])-1 else ''} // {self.feature_names[i]}\n"
        header_content += "};\n\n"
        
        header_content += f"// Quantized model intercept\n"
        header_content += f"const int16_t model_intercept = {quantized_params['intercept']};\n\n"
        
        header_content += f"// Quantized scaler mean values\n"
        header_content += "const int16_t scaler_mean[NUM_FEATURES] = {\n"
        for i, mean in enumerate(quantized_params['mean']):
            header_content += f"    {mean}{',' if i < len(quantized_params['mean'])-1 else ''} // {self.feature_names[i]}\n"
        header_content += "};\n\n"
        
        header_content += f"// Quantized scaler scale values\n"
        header_content += "const int16_t scaler_scale[NUM_FEATURES] = {\n"
        for i, scale in enumerate(quantized_params['scale']):
            header_content += f"    {scale}{',' if i < len(quantized_params['scale'])-1 else ''} // {self.feature_names[i]}\n"
        header_content += "};\n\n"
        
        # Add inference function
        header_content += """
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
"""
        
        # Write to file
        with open('sensor_quality_model.h', 'w') as f:
            f.write(header_content)
        
        print("✅ Header file generated: sensor_quality_model.h")
        
    def run_training_pipeline(self):
        """Run complete lightweight training pipeline"""
        self.load_and_preprocess_data()
        self.engineer_lightweight_features()
        self.create_quality_labels()
        accuracy = self.train_lightweight_model()
        quantized_params = self.quantize_model_parameters()
        self.generate_header_file(quantized_params)
        
        print(f"\n🎉 Lightweight model training completed!")
        print(f"   Final Accuracy: {accuracy:.3f}")
        print(f"   Model Size: ~{len(self.feature_names) * 2 + 10} bytes")
        print(f"   Features: {len(self.feature_names)}")

# Run training
if __name__ == "__main__":
    trainer = LightweightQualityTrainer()
    trainer.run_training_pipeline()
