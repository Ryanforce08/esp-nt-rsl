// ESP32 + Discrete RGB (digital ON/OFF) + WS281x strip control via Serial
// Command format (ASCII line ending with \n):
//   LED <r> <g> <b>   (values 0..255, any nonzero = ON, 0 = OFF)
// Example:
//   LED 255 0 0   -> Red ON

#include <Arduino.h>
#include <FastLED.h>

// -------- Pin Defines --------
#define LED_R 13   // IO13 - Red (digital out)
#define LED_B 14   // IO14 - Blue (digital out)
#define LED_G 15   // IO15 - Green (digital out)

#define WS_PIN    16   // IO16 - WS281x data
#define NUM_LEDS  30

// -------- WS281x setup --------
CRGB leds[NUM_LEDS];

// -------- Serial parsing --------
static String lineBuf;
uint8_t curR = 0, curG = 0, curB = 0;

void setDiscreteRGB(uint8_t r, uint8_t g, uint8_t b) {
  // any nonzero is ON, zero is OFF
  digitalWrite(LED_R, (r > 0) ? HIGH : LOW);
  digitalWrite(LED_G, (g > 0) ? HIGH : LOW);
  digitalWrite(LED_B, (b > 0) ? HIGH : LOW);
}

void setStripRGB(uint8_t r, uint8_t g, uint8_t b) {
  fill_solid(leds, NUM_LEDS, CRGB(r, g, b));
  FastLED.show();
}

void applyColor(uint8_t r, uint8_t g, uint8_t b) {
  curR = r; curG = g; curB = b;
  setDiscreteRGB(r, g, b);
  setStripRGB(r, g, b);
}

void tryHandleLine(const String& s) {
  int r, g, b;
  if (sscanf(s.c_str(), "LED %d %d %d", &r, &g, &b) == 3) {
    r = constrain(r, 0, 255);
    g = constrain(g, 0, 255);
    b = constrain(b, 0, 255);
    applyColor((uint8_t)r, (uint8_t)g, (uint8_t)b);
    Serial.printf("OK LED %d %d %d\n", r, g, b);
  } else {
    unsigned rr, gg, bb;
    if (sscanf(s.c_str(), "HEX #%02x%02x%02x", &rr, &gg, &bb) == 3) {
      applyColor((uint8_t)rr, (uint8_t)gg, (uint8_t)bb);
      Serial.printf("OK HEX #%02X%02X%02X\n", rr, gg, bb);
    } else if (s.length() > 0) {
      Serial.println("ERR Unknown command");
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(50);
  Serial.println("\nESP32 RGB (digital) + WS281x Ready");

  // set pins as outputs
  pinMode(LED_R, OUTPUT);
  pinMode(LED_G, OUTPUT);
  pinMode(LED_B, OUTPUT);

  // Initialize off
  setDiscreteRGB(0, 0, 0);

  // ----- WS281x strip -----
  FastLED.addLeds<NEOPIXEL, WS_PIN>(leds, NUM_LEDS);
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
}

void loop() {
  // Read serial lines (LF-terminated)
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
