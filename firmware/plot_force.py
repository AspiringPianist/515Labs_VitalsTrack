import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from scipy import signal
from scipy.stats import pearsonr
from sklearn.preprocessing import StandardScaler
from sklearn.decomposition import PCA
from sklearn.cluster import KMeans
import glob
import os
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

class VitalsDataAnalyzer:
    def __init__(self, csv_file=None):
        """Initialize analyzer with CSV file"""
        if csv_file is None:
            # Find the most recent CSV file
            csv_files = glob.glob("fsr_*data_*.csv")
            if not csv_files:
                raise FileNotFoundError("No CSV files found. Run data collection first.")
            csv_file = max(csv_files, key=os.path.getctime)
            print(f"📁 Using most recent file: {csv_file}")
        
        self.csv_file = csv_file
        self.df = None
        self.load_data()
        
    def load_data(self):
        """Load and preprocess data"""
        print("📊 Loading data...")
        self.df = pd.read_csv(self.csv_file)
        
        # Convert timestamps
        self.df['Timestamp'] = pd.to_datetime(self.df['Timestamp'])
        self.df['Device_Timestamp'] = pd.to_numeric(self.df['Device_Timestamp'])
        
        # Calculate time differences for sampling rate
        self.df['Time_Diff'] = self.df['Device_Timestamp'].diff()
        
        # Remove outliers (simple method)
        for col in ['IR', 'Red', 'FSR']:
            Q1 = self.df[col].quantile(0.01)
            Q3 = self.df[col].quantile(0.99)
            self.df = self.df[(self.df[col] >= Q1) & (self.df[col] <= Q3)]
        
        print(f"✅ Loaded {len(self.df)} samples")
        print(f"📋 Labels found: {self.df['Label'].unique()}")
        
    def basic_statistics(self):
        """Generate basic statistics"""
        print("\n" + "="*50)
        print("📈 BASIC STATISTICS")
        print("="*50)
        
        # Overall statistics
        print("\n🔢 Overall Statistics:")
        print(self.df[['IR', 'Red', 'FSR']].describe())
        
        # Statistics by label
        print("\n🏷️  Statistics by Label:")
        stats_by_label = self.df.groupby('Label')[['IR', 'Red', 'FSR']].agg(['mean', 'std', 'min', 'max'])
        print(stats_by_label)
        
        # Sampling rate analysis
        avg_sampling_rate = 1000 / self.df['Time_Diff'].mean()  # Convert ms to Hz
        print(f"\n⏱️  Average Sampling Rate: {avg_sampling_rate:.1f} Hz")
        
        return stats_by_label
    
    def plot_raw_data(self):
        """Plot raw sensor data"""
        fig, axes = plt.subplots(3, 1, figsize=(15, 12))
        
        # Color map for labels
        labels = self.df['Label'].unique()
        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        color_map = dict(zip(labels, colors))
        
        # Plot IR data
        for label in labels:
            mask = self.df['Label'] == label
            axes[0].scatter(self.df[mask]['Device_Timestamp'], self.df[mask]['IR'], 
                          c=[color_map[label]], label=label, alpha=0.6, s=1)
        axes[0].set_title('IR Sensor Data Over Time')
        axes[0].set_ylabel('IR Value')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # Plot Red data
        for label in labels:
            mask = self.df['Label'] == label
            axes[1].scatter(self.df[mask]['Device_Timestamp'], self.df[mask]['Red'], 
                          c=[color_map[label]], label=label, alpha=0.6, s=1)
        axes[1].set_title('Red Sensor Data Over Time')
        axes[1].set_ylabel('Red Value')
        axes[1].legend()
        axes[1].grid(True, alpha=0.3)
        
        # Plot FSR data
        for label in labels:
            mask = self.df['Label'] == label
            axes[2].scatter(self.df[mask]['Device_Timestamp'], self.df[mask]['FSR'], 
                          c=[color_map[label]], label=label, alpha=0.6, s=1)
        axes[2].set_title('Force Sensor (FSR) Data Over Time')
        axes[2].set_ylabel('FSR Value')
        axes[2].set_xlabel('Device Timestamp (ms)')
        axes[2].legend()
        axes[2].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('raw_data_plot.png', dpi=300, bbox_inches='tight')
        plt.show()
    
    def plot_distributions(self):
        """Plot data distributions"""
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        # Histograms
        self.df['IR'].hist(bins=50, ax=axes[0,0], alpha=0.7)
        axes[0,0].set_title('IR Distribution')
        axes[0,0].set_xlabel('IR Value')
        
        self.df['Red'].hist(bins=50, ax=axes[0,1], alpha=0.7)
        axes[0,1].set_title('Red Distribution')
        axes[0,1].set_xlabel('Red Value')
        
        self.df['FSR'].hist(bins=50, ax=axes[0,2], alpha=0.7)
        axes[0,2].set_title('FSR Distribution')
        axes[0,2].set_xlabel('FSR Value')
        
        # Box plots by label
        sns.boxplot(data=self.df, x='Label', y='IR', ax=axes[1,0])
        axes[1,0].set_title('IR by Label')
        axes[1,0].tick_params(axis='x', rotation=45)
        
        sns.boxplot(data=self.df, x='Label', y='Red', ax=axes[1,1])
        axes[1,1].set_title('Red by Label')
        axes[1,1].tick_params(axis='x', rotation=45)
        
        sns.boxplot(data=self.df, x='Label', y='FSR', ax=axes[1,2])
        axes[1,2].set_title('FSR by Label')
        axes[1,2].tick_params(axis='x', rotation=45)
        
        plt.tight_layout()
        plt.savefig('distributions_plot.png', dpi=300, bbox_inches='tight')
        plt.show()
    
    def correlation_analysis(self):
        """Analyze correlations between sensors"""
        print("\n" + "="*50)
        print("🔗 CORRELATION ANALYSIS")
        print("="*50)
        
        # Overall correlations
        corr_matrix = self.df[['IR', 'Red', 'FSR']].corr()
        print("\n📊 Overall Correlations:")
        print(corr_matrix)
        
        # Correlation by label
        print("\n🏷️  Correlations by Label:")
        for label in self.df['Label'].unique():
            label_data = self.df[self.df['Label'] == label]
            if len(label_data) > 10:  # Need enough data points
                ir_red_corr = pearsonr(label_data['IR'], label_data['Red'])[0]
                ir_fsr_corr = pearsonr(label_data['IR'], label_data['FSR'])[0]
                red_fsr_corr = pearsonr(label_data['Red'], label_data['FSR'])[0]
                
                print(f"{label}:")
                print(f"  IR-Red: {ir_red_corr:.3f}")
                print(f"  IR-FSR: {ir_fsr_corr:.3f}")
                print(f"  Red-FSR: {red_fsr_corr:.3f}")
        
        # Plot correlation heatmap
        plt.figure(figsize=(8, 6))
        sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0)
        plt.title('Sensor Correlation Matrix')
        plt.tight_layout()
        plt.savefig('correlation_heatmap.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        return corr_matrix
    
    def signal_processing_analysis(self):
        """Advanced signal processing analysis"""
        print("\n" + "="*50)
        print("🌊 SIGNAL PROCESSING ANALYSIS")
        print("="*50)
        
        # Calculate sampling rate
        sampling_rate = 1000 / self.df['Time_Diff'].mean()  # Hz
        
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        for i, sensor in enumerate(['IR', 'Red', 'FSR']):
            # Get clean signal for each label
            for label in self.df['Label'].unique():
                label_data = self.df[self.df['Label'] == label][sensor].values
                
                if len(label_data) > 100:  # Need enough data for FFT
                    # Apply smoothing
                    smoothed = signal.savgol_filter(label_data, 11, 3)
                    
                    # FFT for frequency analysis
                    fft = np.fft.fft(smoothed)
                    freqs = np.fft.fftfreq(len(fft), 1/sampling_rate)
                    
                    # Plot time domain (smoothed)
                    axes[0, i].plot(smoothed[:200], label=f'{label}', alpha=0.7)
                    
                    # Plot frequency domain (magnitude)
                    axes[1, i].plot(freqs[:len(freqs)//2], 
                                   np.abs(fft[:len(fft)//2]), 
                                   label=f'{label}', alpha=0.7)
            
            axes[0, i].set_title(f'{sensor} - Time Domain (Smoothed)')
            axes[0, i].set_xlabel('Sample')
            axes[0, i].set_ylabel('Value')
            axes[0, i].legend()
            axes[0, i].grid(True, alpha=0.3)
            
            axes[1, i].set_title(f'{sensor} - Frequency Domain')
            axes[1, i].set_xlabel('Frequency (Hz)')
            axes[1, i].set_ylabel('Magnitude')
            axes[1, i].set_xlim(0, 5)  # Focus on low frequencies
            axes[1, i].legend()
            axes[1, i].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('signal_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()
    
    def machine_learning_analysis(self):
        """Basic ML analysis for pattern recognition"""
        print("\n" + "="*50)
        print("🤖 MACHINE LEARNING ANALYSIS")
        print("="*50)
        
        # Prepare data
        features = ['IR', 'Red', 'FSR']
        X = self.df[features].values
        
        # Standardize features
        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)
        
        # PCA Analysis
        pca = PCA(n_components=2)
        X_pca = pca.fit_transform(X_scaled)
        
        print(f"📊 PCA Explained Variance Ratio: {pca.explained_variance_ratio_}")
        
        # K-means clustering
        kmeans = KMeans(n_clusters=len(self.df['Label'].unique()), random_state=42)
        clusters = kmeans.fit_predict(X_scaled)
        
        # Plot PCA results
        fig, axes = plt.subplots(1, 2, figsize=(15, 6))
        
        # PCA colored by actual labels
        labels = self.df['Label'].unique()
        colors = plt.cm.Set3(np.linspace(0, 1, len(labels)))
        
        for i, label in enumerate(labels):
            mask = self.df['Label'] == label
            axes[0].scatter(X_pca[mask, 0], X_pca[mask, 1], 
                          c=[colors[i]], label=label, alpha=0.6)
        
        axes[0].set_title('PCA - Colored by Actual Labels')
        axes[0].set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]:.2%} variance)')
        axes[0].set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]:.2%} variance)')
        axes[0].legend()
        axes[0].grid(True, alpha=0.3)
        
        # PCA colored by clusters
        scatter = axes[1].scatter(X_pca[:, 0], X_pca[:, 1], c=clusters, cmap='viridis', alpha=0.6)
        axes[1].set_title('PCA - Colored by K-means Clusters')
        axes[1].set_xlabel(f'PC1 ({pca.explained_variance_ratio_[0]:.2%} variance)')
        axes[1].set_ylabel(f'PC2 ({pca.explained_variance_ratio_[1]:.2%} variance)')
        plt.colorbar(scatter, ax=axes[1])
        axes[1].grid(True, alpha=0.3)
        
        plt.tight_layout()
        plt.savefig('ml_analysis.png', dpi=300, bbox_inches='tight')
        plt.show()
        
        return X_pca, clusters
    
    def derive_insights(self):
        """Derive key insights from the data"""
        print("\n" + "="*50)
        print("💡 KEY INSIGHTS")
        print("="*50)
        
        insights = []
        
        # 1. Data quality insights
        total_samples = len(self.df)
        sampling_rate = 1000 / self.df['Time_Diff'].mean()
        insights.append(f"📊 Collected {total_samples} samples at ~{sampling_rate:.1f} Hz")
        
        # 2. Label distribution
        label_counts = self.df['Label'].value_counts()
        insights.append(f"🏷️  Most common label: '{label_counts.index[0]}' ({label_counts.iloc[0]} samples)")
        
        # 3. Sensor range insights
        # 3. Sensor range insights
        for sensor in ['IR', 'Red', 'FSR']:
            sensor_range = self.df[sensor].max() - self.df[sensor].min()
            sensor_mean = self.df[sensor].mean()
            sensor_std = self.df[sensor].std()
            cv = (sensor_std / sensor_mean) * 100  # Coefficient of variation
            insights.append(f"📈 {sensor}: Range={sensor_range:.0f}, Mean={sensor_mean:.0f}, CV={cv:.1f}%")
        
        # 4. Label-specific insights
        stats_by_label = self.df.groupby('Label')[['IR', 'Red', 'FSR']].mean()
        
        # Find most distinguishable sensor
        label_variance = {}
        for sensor in ['IR', 'Red', 'FSR']:
            label_variance[sensor] = stats_by_label[sensor].var()
        
        best_sensor = max(label_variance, key=label_variance.get)
        insights.append(f"🎯 Most discriminative sensor: {best_sensor} (highest variance between labels)")
        
        # 5. Correlation insights
        corr_matrix = self.df[['IR', 'Red', 'FSR']].corr()
        ir_red_corr = corr_matrix.loc['IR', 'Red']
        
        if abs(ir_red_corr) > 0.7:
            insights.append(f"🔗 Strong correlation between IR and Red sensors ({ir_red_corr:.3f})")
        elif abs(ir_red_corr) < 0.3:
            insights.append(f"🔗 Weak correlation between IR and Red sensors ({ir_red_corr:.3f})")
        
        # 6. Force sensor insights
        fsr_labels = self.df.groupby('Label')['FSR'].mean().sort_values(ascending=False)
        highest_force_label = fsr_labels.index[0]
        lowest_force_label = fsr_labels.index[-1]
        insights.append(f"💪 Highest force detected in: '{highest_force_label}' ({fsr_labels.iloc[0]:.0f})")
        insights.append(f"🪶 Lowest force detected in: '{lowest_force_label}' ({fsr_labels.iloc[-1]:.0f})")
        
        # 7. Signal quality insights
        for sensor in ['IR', 'Red']:
            sensor_data = self.df[sensor]
            # Simple noise estimation using high-frequency content
            diff_std = sensor_data.diff().std()
            signal_std = sensor_data.std()
            snr_estimate = signal_std / diff_std if diff_std > 0 else float('inf')
            
            if snr_estimate > 10:
                quality = "Good"
            elif snr_estimate > 5:
                quality = "Fair"
            else:
                quality = "Noisy"
            
            insights.append(f"📡 {sensor} signal quality: {quality} (SNR≈{snr_estimate:.1f})")
        
        # 8. Temporal insights
        collection_duration = (self.df['Device_Timestamp'].max() - self.df['Device_Timestamp'].min()) / 1000
        insights.append(f"⏱️  Total collection time: {collection_duration:.1f} seconds")
        
        # Print all insights
        for insight in insights:
            print(insight)
        
        return insights
    
    def generate_report(self):
        """Generate a comprehensive analysis report"""
        print("\n" + "="*60)
        print("📋 COMPREHENSIVE ANALYSIS REPORT")
        print("="*60)
        
        # Run all analyses
        stats = self.basic_statistics()
        corr_matrix = self.correlation_analysis()
        insights = self.derive_insights()
        
        # Generate plots
        print("\n📊 Generating visualizations...")
        self.plot_raw_data()
        self.plot_distributions()
        self.signal_processing_analysis()
        pca_data, clusters = self.machine_learning_analysis()
        
        # Save summary report
        report_filename = f"analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(report_filename, 'w') as f:
            f.write("VITALS TRACK DATA ANALYSIS REPORT\n")
            f.write("="*50 + "\n\n")
            f.write(f"Data File: {self.csv_file}\n")
            f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            
            f.write("KEY INSIGHTS:\n")
            f.write("-" * 20 + "\n")
            for insight in insights:
                f.write(f"{insight}\n")
            
            f.write(f"\nSTATISTICS BY LABEL:\n")
            f.write("-" * 20 + "\n")
            f.write(str(stats))
            
            f.write(f"\n\nCORRELATION MATRIX:\n")
            f.write("-" * 20 + "\n")
            f.write(str(corr_matrix))
        
        print(f"📄 Report saved to: {report_filename}")
        print("🖼️  Plots saved as PNG files")
        
        return report_filename

def main():
    """Main analysis function"""
    print("🔬 VitalsTrack Data Analyzer")
    print("=" * 40)
    
    try:
        # Initialize analyzer
        analyzer = VitalsDataAnalyzer()
        
        # Generate comprehensive report
        report_file = analyzer.generate_report()
        
        print(f"\n✅ Analysis complete!")
        print(f"📊 Check the generated plots and {report_file} for detailed insights")
        
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        print("💡 Make sure you have collected data first using test_force.py")
    except Exception as e:
        print(f"❌ Analysis error: {e}")

if __name__ == "__main__":
    main()
