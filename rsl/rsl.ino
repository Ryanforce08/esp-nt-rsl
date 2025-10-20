// ESP32 + Discrete RGB (digital ON/OFF) + WS281x strip control via Serial
// Command format (ASCII line ending with \n):
//   LED <r> <g> <b>   (values 0..255, any nonzero = ON, 0 = OFF)
// Example:
//   LED 255 0 0   -> Red ON

#include <Arduino.h>
#include <FastLED.h>

// -------- Pin Defines --------
#define LED_R 13  // IO3 - Red (digital out)
#define LED_B 12  // IO4 - Blue (digital out)
#define LED_G 14  // IO6 - Green (digital out)

#define WS_PIN 22  // IO16 - WS281x data
#define NUM_LEDS 144

#define LIMIT_PIN 12   // IO12 - get is the gate is closed (digital in)
#define MANUAL_PIN 13  //IO13 - get if manual is on (digital in)

// -------- WS281x setup --------
CRGB leds[NUM_LEDS];

// -------- Serial parsing --------
static String lineBuf;
uint8_t curR = 0, curG = 0, curB = 0;

// -------- Heartbeat -------------
unsigned long lastPingTime = 0;
bool pcAlive = false;

void setDiscreteRGB(uint8_t r, uint8_t g, uint8_t b) {
  analogWrite(LED_R, r);
  analogWrite(LED_G, g);
  analogWrite(LED_B, b);
}

void setStripRGB(uint8_t r, uint8_t g, uint8_t b) {
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

void tryHandleLine(const String& s) {
  int r, g, b;
  if (sscanf(s.c_str(), "LED %d %d %d", &r, &g, &b) == 3) {
    r = constrain(r, 0, 255);
    g = constrain(g, 0, 255);
    b = constrain(b, 0, 255);
    applyColor((uint8_t)r, (uint8_t)g, (uint8_t)b);
    Serial.printf("OK LED %d %d %d\n", r, g, b);
  } else if (s == "Hallo"){
    lastPingTime = millis();
    pcAlive = true;
  }
  else {
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
  pinMode(LIMIT_PIN, INPUT);
  pinMode(MANUAL_PIN, INPUT);

  // Initialize off
  setDiscreteRGB(0, 0, 0);

  // ----- WS281x strip -----
  FastLED.addLeds<NEOPIXEL, WS_PIN>(leds, NUM_LEDS);
  fill_solid(leds, NUM_LEDS, CRGB::Black);
  FastLED.show();
  // lastPingTime = millis();
}

void loop() {
  // --- Timeout check ---
  if (millis() - lastPingTime > 2000) {
    if (pcAlive == true) {
      Serial.println("Lost Comms");
    }
    pcAlive = false;
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

  // --- Behavior based on mode ---
  if ((digitalRead(MANUAL_PIN) == HIGH) || (pcAlive == false)) {
    // Manual or lost PC connection
    if (digitalRead(LIMIT_PIN) == HIGH)
      applyColor((uint8_t)255, (uint8_t)0, (uint8_t)0);
    else
      applyColor((uint8_t)0, (uint8_t)255, (uint8_t)0);
  } 
  else {
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
}