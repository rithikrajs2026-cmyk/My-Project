#include <WiFi.h>
#include <ArduinoJson.h> 

const char* ssid     = "YOUR_WIFI_NAME";
const char* password = "YOUR_WIFI_PASSWORD";
const char* host = "192.168.1.100"; // REPLACE WITH RASPBERRY PI IP
const uint16_t port = 65432;

#define PIN_TDS       32
#define PIN_PH        34
#define PIN_TURBIDITY 35

float vRef = 3.3;      
float adcResolution = 4095.0;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12); 
  pinMode(PIN_PH, INPUT);
  pinMode(PIN_TURBIDITY, INPUT);
  pinMode(PIN_TDS, INPUT);

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
}

int getAverageReading(int pin) {
  long sum = 0;
  for(int i=0; i<10; i++) {
    sum += analogRead(pin);
    delay(10);
  }
  return sum / 10;
}

void loop() {
  int phRaw = getAverageReading(PIN_PH);
  int turbRaw = getAverageReading(PIN_TURBIDITY);
  int tdsRaw = getAverageReading(PIN_TDS);

  float phVolt = phRaw * (vRef / adcResolution);
  float turbVolt = turbRaw * (vRef / adcResolution);
  float tdsVolt = tdsRaw * (vRef / adcResolution);
  
  float phValue = 3.5 * phVolt + 0.0; 
  float turbidityValue = map(turbRaw, 0, 4095, 100, 0); 
  if (turbidityValue < 0) turbidityValue = 0;
  float tdsValue = (tdsVolt * 1000) * 0.5; 

  StaticJsonDocument<200> doc;
  doc["ph"] = phValue;
  doc["turbidity"] = turbidityValue;
  doc["tds"] = tdsValue;

  String jsonString;
  serializeJson(doc, jsonString);

  WiFiClient client;
  if (client.connect(host, port)) {
    client.print(jsonString);
    client.stop();
  }

  delay(2000); 
}
