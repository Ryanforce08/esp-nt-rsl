// ESP32 + Discrete RGB (digital ON/OFF) + WS281x strip control via Serial
// Command format (ASCII line ending with \n):
//   LED <r> <g> <b>   (values 0..255, any nonzero = ON, 0 = OFF)
// Example:
//   LED 255 0 0   -> Red ON

#include <Arduino.h>
#include <FastLED.h>

// -------- Pin Defines --------
#define LED_R 27  // IO3 - Red (digital out)
#define LED_B 12  // IO4 - Blue (digital out)
#define LED_G 14  // IO6 - Green (digital out)

#define WS_PIN 22  // IO16 - WS281x data
#define NUM_LEDS 144

#define LIMIT_PIN 12   // IO12 - get is the gate is closed (digital in)
#define MANUAL_PIN 13  //IO13 - get if manual is on (digital in)
#define VOLUME_PIN 32

const int sampleCount = 9;  // Number of samples for median filter
const float alpha = 0.1;    // Smoothing factor (0.0–1.0)
float smoothedValue = 0;

double brightness = 0.5;
// -------- WS281x setup --------
CRGB leds[NUM_LEDS];

// -------- Serial parsing --------
static String lineBuf;
uint8_t curR = 0, curG = 0, curB = 0;

// -------- Heartbeat -------------
unsigned long lastPingTime = 0;
bool pcAlive = false;

String curr_led = "RGBIS";

void updateCurrentRGB(int r,int g, int b) {
  String s = "RGBIS ";
  s += r;
  s += " ";
  s += g;
  s += " ";
  s += b;
  curr_led = s;
}

void setDiscreteRGB(uint8_t r, uint8_t g, uint8_t b) {
  // analogWrite(LED_R, r);
  // analogWrite(LED_G, g);
  // analogWrite(LED_B, b);
}

void setStripRGB(uint8_t r, uint8_t g, uint8_t b) {
  if ((digitalRead(MANUAL_PIN) == LOW))
    updateCurrentRGB(r,g,b);
  fill_solid(leds, NUM_LEDS, CRGB(r, g, b));
  FastLED.show();
}

void applyColor(uint8_t r, uint8_t g, uint8_t b) {
  curR = r;
  curG = g;
  curB = b;
  setDiscreteRGB(r, g, b);
  setStripRGB(r, g, b);
}

struct Command {
  const char* name;
  void (*handler)(const String&);
};

void cmdLED(const String& s) {
  int r, g, b;
  if (sscanf(s.c_str(), "LED %d %d %d", &r, &g, &b) == 3)
    setStripRGB(r, g, b);
}

void cmdHEX(const String& s) {
  unsigned rr, gg, bb;
  if (sscanf(s.c_str(), "HEX #%02x%02x%02x", &rr, &gg, &bb) == 3)
    setStripRGB(rr, gg, bb);
}

void cmdHallo(const String& s) {
  lastPingTime = millis();
  pcAlive = true;
}

void cmdRainbow(const String& s) {
  fill_rainbow(leds, NUM_LEDS,0);
}

void cmdGetRGB(const String& s) {
  Serial.println(curr_led);
}


Command commands[] = {
  {"LED", cmdLED},
  {"HEX", cmdHEX},
  {"Hallo", cmdHallo},
  {"RAINBOW", cmdRainbow},
  {"GETRGB", cmdGetRGB}
};

void tryHandleLine(const String& s) {
  for (auto& cmd : commands) {
    if (s.startsWith(cmd.name)) {
      cmd.handler(s);
      // Serial.printf("OK %s\n", cmd.name);
      return;
    }
  }
  Serial.println("ERR Unknown command");
}

void readSerial() {
  while (Serial.available()) {
      char c = (char)Serial.read();
      if (c == '\n') {
        String s = lineBuf;
        if (s.endsWith("\r")) s.remove(s.length() - 1);
        tryHandleLine(s);
        lineBuf = "";
      } else {
        lineBuf += c;
        if (lineBuf.length() > 200) lineBuf.remove(0, 200);
      }
  }
}
int medianFilter() {
  int readings[sampleCount];
  for (int i = 0; i < sampleCount; i++) {
    readings[i] = analogRead(VOLUME_PIN);
    delayMicroseconds(500);
  }

  // Sort the readings (simple bubble sort)
  for (int i = 0; i < sampleCount - 1; i++) {
    for (int j = i + 1; j < sampleCount; j++) {
      if (readings[j] < readings[i]) {
        int temp = readings[i];
        readings[i] = readings[j];
        readings[j] = temp;
      }
    }
  }

  // Return median (middle value)
  return readings[sampleCount / 2];
}


void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.println("\nESP32 RGB (digital) + WS281x Ready");

  // set pins as outputs
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);
  pinMode(LIMIT_PIN, INPUT);
  pinMode(MANUAL_PIN, INPUT);

  // Initialize off
  setDiscreteRGB(0, 0, 0);

  // ----- WS281x strip -----
  FastLED.addLeds<NEOPIXEL, WS_PIN>(leds, NUM_LEDS);
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
  // analogSetAttenuation(ADC_11db);
  // lastPingTime = millis();
}

void loop() {
  // --- Timeout check ---
  if (millis() - lastPingTime > 2000) {
    if (pcAlive == true) {
      Serial.println("Lost Comms");
    }
    pcAlive = false;
    readSerial();;
  }
  int filtered = medianFilter();  // Remove spikes
  smoothedValue = alpha * filtered + (1 - alpha) * smoothedValue;  // Smooth changes
  brightness = (smoothedValue / 4095);

  // --- Behavior based on mode ---
  if ((digitalRead(MANUAL_PIN) == HIGH) || (pcAlive == false)) {
    // Manual or lost PC connection
    if (digitalRead(LIMIT_PIN) == HIGH) {
      if ((pcAlive == false) || (digitalRead(MANUAL_PIN) == HIGH)) {
        setStripRGB((uint8_t)255 * brightness, (uint8_t)0, (uint8_t)0);
      }

    }
    else {
      setStripRGB((uint8_t)0, (uint8_t)255 * brightness, (uint8_t)0);
      if ((pcAlive == true) || (digitalRead(MANUAL_PIN) == LOW)) {
        return;
      }
    }
  } 
  else {
    // Read serial lines (LF-terminated)
    readSerial();
  }
}