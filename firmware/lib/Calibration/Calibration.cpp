/*****************************************************************************/
//	Function:	 To calibrate the parameters and it will recommend parameter
//				setting and print to the serial monitor.So the values of the
//				marco definitions in the ADXL335.h should be modified.
//  Hardware:    Grove - 3-Axis Analog Accelerometer
//	Arduino IDE: Arduino-1.0
//	Author:	 Frankie.Chu
//	Date: 	 Jan 11,2013
//	Version: v1.0
//	by www.seeedstudio.com
//
//  This library is free software; you can redistribute it and/or
//  modify it under the terms of the GNU Lesser General Public
//  License as published by the Free Software Foundation; either
//  version 2.1 of the License, or (at your option) any later version.
//
//  This library is distributed in the hope that it will be useful,
//  but WITHOUT ANY WARRANTY; without even the implied warranty of
//  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
//  Lesser General Public License for more details.
//
//  You should have received a copy of the GNU Lesser General Public
//  License along with this library; if not, write to the Free Software
//  Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA
//
/*******************************************************************************/
#include <Arduino.h>
#include "ADXL335.h"
int zero_x;
int zero_y;
int zero_z;
int max_x, max_y, max_z; //when 1g
float sensitivity;
ADXL335 accelerometer;
void setup() {
    Serial.begin(9600);
    accelerometer.begin();
    int x, y, z;
    for (int i = 0; i < 20; i ++) {
        accelerometer.getXYZ(&x, &y, &z);
    }
    Serial.println("The calibration starts: ");
    Serial.println("First, make sure that Z-axis direction is straight up");
    Serial.println("please type any charactor if you are ready");
    while (Serial.available() == 0);
    delay(100);
    while (Serial.available() > 0) {
        Serial.read();
    }
    calibrate(&x, &y, &z);
    zero_x = x;
    zero_y = y;
    max_z = z;
    Serial.println("Second, make sure that X-axis direction is straight up");
    Serial.println("please type any charactor again if you are ready");
    while (Serial.available() == 0);
    delay(100);
    while (Serial.available() > 0) {
        Serial.read();
    }
    calibrate(&x, &y, &z);
    zero_z = z;
float zero_xv = zero_x * ADC_REF / ADC_AMPLITUDE;
float zero_yv = zero_y * ADC_REF / ADC_AMPLITUDE;
float zero_zv = zero_z * ADC_REF / ADC_AMPLITUDE;
sensitivity = (float)(max_z - zero_z) * ADC_REF / ADC_AMPLITUDE;

Serial.println("Copy the following into ADXL335.h:");
Serial.printf("#define ZERO_X %.2f\n", zero_xv);
Serial.printf("#define ZERO_Y %.2f\n", zero_yv);
Serial.printf("#define ZERO_Z %.2f\n", zero_zv);
Serial.printf("#define SENSITIVITY %.2f\n", sensitivity);

    Serial.println("please modified the macro definitions with these results in ADXL335.h");
}
void loop() {

}
void calibrate(int* _x, int* _y, int* _z) {
    int sum_x = 0, sum_y = 0, sum_z = 0;
    for (int i = 0; i < 50; i++) {
        int x, y, z;
        accelerometer.getXYZ(&x, &y, &z);
        sum_x += x;
        sum_y += y;
        sum_z += z;
        delay(10);  // reduce noise
    }
    *_x = sum_x / 50;
    *_y = sum_y / 50;
    *_z = sum_z / 50;
}
