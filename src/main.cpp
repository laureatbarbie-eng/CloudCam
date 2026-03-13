#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <time.h>
#include <esp_task_wdt.h>

// ------------------- CONFIG -------------------
static const char* WIFI_SSID = "Raspberry";
static const char* WIFI_PASS = "12345678";
static const char* SERVER_HOST = "192.168.4.1";
static const uint16_t SERVER_PORT = 8000;
static const char* CAM_ID = "cam160";

static const uint32_t CAPTURE_PERIOD_SEC = 600;
static const uint32_t FAIL_SLEEP_SEC = 120;
static const uint32_t CHUNK_SIZE = 2048;
static const uint8_t UPLOAD_MAX_RETRIES = 3;
static const uint8_t CHUNK_MAX_RETRIES = 5;

static const uint32_t WIFI_TIMEOUT_MS = 15000;
static const uint32_t CMD_TOTAL_WAIT_MS = 50000;
static const uint32_t ACK_TOTAL_WAIT_MS = 60000;

// SNTP: увеличенный таймаут + retry (но необязательный для синхронизации)
static const uint32_t SNTP_TIMEOUT_MS = 15000;
static const uint8_t SNTP_MAX_RETRIES = 3;

static const uint32_t HTTP_SOCK_TIMEOUT_MS = 5000;
static const uint32_t CHUNK_SOCK_TIMEOUT_MS = 8000;

static const bool WIFI_DISABLE_SLEEP = true;
static const bool WIFI_MAX_TXPOWER = true;

static const size_t TCP_WRITE_BLOCK = 1460;

#define LED_FLASH_GPIO GPIO_NUM_4
#define STATUS_LED_GPIO GPIO_NUM_33

// ------------------- CRC32 -------------------
static uint32_t crc32_table[256];
static bool crc32_table_computed = false;

static void make_crc32_table() {
  if (crc32_table_computed) return;
  for (uint32_t n = 0; n < 256; n++) {
    uint32_t c = n;
    for (int k = 0; k < 8; k++) {
      c = (c & 1) ? (0xedb88320UL ^ (c >> 1)) : (c >> 1);
    }
    crc32_table[n] = c;
  }
  crc32_table_computed = true;
}

static uint32_t crc32(const uint8_t *buf, size_t len) {
  make_crc32_table();
  uint32_t c = 0xffffffffUL;
  for (size_t n = 0; n < len; n++) {
    c = crc32_table[(c ^ buf[n]) & 0xff] ^ (c >> 8);
  }
  return c ^ 0xffffffffUL;
}

// ------------------- Helpers -------------------
static uint32_t ms() { return millis(); }

static void goToSleep(uint32_t seconds) {
  Serial.printf("[SLEEP] %u sec\n", seconds);
  esp_sleep_enable_timer_wakeup((uint64_t)seconds * 1000000ULL);
  esp_deep_sleep_start();
}

static void blinkStatus(uint8_t times, uint16_t onms, uint16_t offms) {
  for (uint8_t i = 0; i < times; i++) {
    digitalWrite(STATUS_LED_GPIO, LOW);
    delay(onms);
    digitalWrite(STATUS_LED_GPIO, HIGH);
    delay(offms);
  }
}

static bool readLine(WiFiClient &c, String &line, uint32_t timeoutMs) {
  line = "";
  uint32_t t0 = ms();
  while (ms() - t0 < timeoutMs) {
    while (c.available()) {
      char ch = (char)c.read();
      if (ch == '\r') continue;
      if (ch == '\n') return true;
      line += ch;
    }
    if (!c.connected()) return line.length() > 0;
    delay(1);
  }
  return false;
}

struct HttpResp {
  int status = -1;
  String body;
};

static bool httpRequestRaw(const String &req, HttpResp &out, uint32_t totalTimeoutMs) {
  out = HttpResp();

  WiFiClient client;
  if (!client.connect(SERVER_HOST, SERVER_PORT)) return false;
  client.setTimeout(HTTP_SOCK_TIMEOUT_MS);

  client.print(req);
  uint32_t t0 = ms();

  String statusLine;
  if (!readLine(client, statusLine, 3000)) { client.stop(); return false; }

  int sp = statusLine.indexOf(' ');
  if (sp < 0) { client.stop(); return false; }
  int sp2 = statusLine.indexOf(' ', sp + 1);
  String codeStr = (sp2 > sp) ? statusLine.substring(sp + 1, sp2) : statusLine.substring(sp + 1);
  out.status = codeStr.toInt();

  int contentLen = -1;
  while (true) {
    String h;
    if (!readLine(client, h, 3000)) { client.stop(); return false; }
    if (h.length() == 0) break;
    String hl = h; hl.toLowerCase();
    if (hl.startsWith("content-length:")) contentLen = hl.substring(15).toInt();
    if (ms() - t0 > totalTimeoutMs) { client.stop(); return false; }
  }

  String body;
  if (contentLen >= 0) body.reserve(contentLen + 8);

  if (contentLen >= 0) {
    while ((int)body.length() < contentLen && (ms() - t0 < totalTimeoutMs)) {
      while (client.available() && (int)body.length() < contentLen)
        body += (char)client.read();
      if (!client.connected() && !client.available()) break;
      delay(1);
    }
  } else {
    while (ms() - t0 < totalTimeoutMs) {
      while (client.available()) body += (char)client.read();
      if (!client.connected() && !client.available()) break;
      delay(1);
    }
  }

  client.stop();
  body.trim();
  out.body = body;
  return true;
}

static bool jsonFindInt(const String &json, const char *key, int &out) {
  String pat = String("\"") + key + "\":";
  int idx = json.indexOf(pat);
  if (idx < 0) return false;
  int colon = json.indexOf(':', idx);
  if (colon < 0) return false;
  colon++;
  while (colon < (int)json.length() && (json[colon] == ' ' || json[colon] == '"')) colon++;
  String num = "";
  while (colon < (int)json.length() && (isdigit(json[colon]) || json[colon] == '-'))
    num += json[colon++];
  if (num.length() == 0) return false;
  out = num.toInt();
  return true;
}

static bool jsonFindString(const String &json, const char *key, String &out) {
  String pat = String("\"") + key + "\":\"";
  int idx = json.indexOf(pat);
  if (idx < 0) return false;
  idx += pat.length();
  int end = json.indexOf('"', idx);
  if (end < 0) return false;
  out = json.substring(idx, end);
  return true;
}

static bool jsonFindBool(const String &json, const char *key, bool &out) {
  String pat = String("\"") + key + "\":";
  int idx = json.indexOf(pat);
  if (idx < 0) return false;
  int colon = json.indexOf(':', idx);
  if (colon < 0) return false;
  colon++;
  while (colon < (int)json.length() && json[colon] == ' ') colon++;
  if (json.substring(colon).startsWith("true")) { out = true; return true; }
  if (json.substring(colon).startsWith("false")) { out = false; return true; }
  return false;
}

static void wifiTuneAfterConnect() {
  if (WIFI_DISABLE_SLEEP) WiFi.setSleep(false);
  if (WIFI_MAX_TXPOWER) WiFi.setTxPower(WIFI_POWER_19_5dBm);
}

static bool connectWiFi(uint32_t timeoutMs) {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  uint32_t t0 = ms();
  while (WiFi.status() != WL_CONNECTED && (ms() - t0 < timeoutMs)) {
    delay(50);
    esp_task_wdt_reset();
  }
  if (WiFi.status() != WL_CONNECTED) return false;
  wifiTuneAfterConnect();
  return true;
}

// SNTP с retry логикой (необязательный результат)
static bool syncTimeSNTP() {
  configTime(0, 0, SERVER_HOST);
  
  for (uint8_t attempt = 1; attempt <= SNTP_MAX_RETRIES; attempt++) {
    uint32_t t0 = ms();
    struct tm ti;
    
    while (ms() - t0 < SNTP_TIMEOUT_MS) {
      esp_task_wdt_reset();
      if (getLocalTime(&ti, 200)) {
        Serial.printf("[SNTP] Synced on attempt %d\n", attempt);
        return true;
      }
      delay(50);
    }
    
    if (attempt < SNTP_MAX_RETRIES) {
      Serial.printf("[SNTP] Attempt %d failed, retrying...\n", attempt);
      delay(1000);
    }
  }
  
  Serial.println("[SNTP] All attempts failed, continuing without time sync");
  return false;
}

// ------------------- Camera Init OV5640 -------------------
static void startCameraOV5640() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  
  config.pin_d0 = 5;
  config.pin_d1 = 18;
  config.pin_d2 = 19;
  config.pin_d3 = 21;
  config.pin_d4 = 36;
  config.pin_d5 = 39;
  config.pin_d6 = 34;
  config.pin_d7 = 35;
  config.pin_xclk = 0;
  config.pin_pclk = 22;
  config.pin_vsync = 25;
  config.pin_href = 23;
  config.pin_sccb_sda = 26;
  config.pin_sccb_scl = 27;
  config.pin_pwdn = 32;
  config.pin_reset = -1;

  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (!psramFound()) {
    Serial.println("[ERR] PSRAM NOT FOUND - HALTING");
    while (true) delay(1000);
  }

  config.frame_size = FRAMESIZE_QXGA;
  config.jpeg_quality = 10;
  config.fb_count = 1;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("[ERR] Camera init failed: 0x%x\n", err);
    while (true) delay(1000);
  }

  sensor_t *s = esp_camera_sensor_get();
  if (s) {
    s->set_brightness(s, 0);
    s->set_contrast(s, 0);
    s->set_saturation(s, 0);
    s->set_whitebal(s, 1);
    s->set_awb_gain(s, 1);
    s->set_exposure_ctrl(s, 1);
    s->set_gain_ctrl(s, 1);
    s->set_gainceiling(s, (gainceiling_t)2);
    s->set_lenc(s, 1);
    s->set_raw_gma(s, 1);
    s->set_bpc(s, 0);
    s->set_wpc(s, 1);
    s->set_hmirror(s, 0);
    s->set_vflip(s, 0);
  }
  
  Serial.println("[OK] OV5640 initialized");
  Serial.printf("[INFO] Resolution: QXGA (2048x1536), XCLK: 20MHz\n");
}

// ------------------- API Calls -------------------
static bool postHello(int &cycleIdOut, int &delayMsOut) {
  String payload = String("{\"deviceid\":\"") + CAM_ID + "\",\"local_ms\":" + String(ms()) + "}";
  String req =
      String("POST /hello HTTP/1.1\r\n") +
      "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
      "Connection: close\r\n" +
      "Content-Type: application/json\r\n" +
      "Content-Length: " + String(payload.length()) + "\r\n\r\n" +
      payload;

  HttpResp r;
  if (!httpRequestRaw(req, r, 7000)) return false;
  if (r.status != 200) return false;

  int cid = -1, delay_ms = -1;
  if (!jsonFindInt(r.body, "cycle_id", cid)) return false;
  if (!jsonFindInt(r.body, "capture_delay_ms", delay_ms)) return false;
  cycleIdOut = cid;
  delayMsOut = delay_ms;
  return true;
}

static bool waitCmd(int cycleId, int &captureMsOut) {
  uint32_t t0 = ms();
  while (ms() - t0 < CMD_TOTAL_WAIT_MS) {
    esp_task_wdt_reset();
    String path = String("/waitcmd?deviceid=") + CAM_ID + "&cycle_id=" + String(cycleId) + "&local_ms=" + String(ms());
    String req =
        String("GET ") + path + " HTTP/1.1\r\n" +
        "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
        "Connection: close\r\n\r\n";

    HttpResp r;
    if (!httpRequestRaw(req, r, 35000)) { delay(100); continue; }
    if (r.status != 200) { delay(100); continue; }

    if (r.body.indexOf("\"type\":\"CAPTURE_AT\"") >= 0) {
      int delay_ms = -1;
      if (!jsonFindInt(r.body, "capture_delay_ms", delay_ms)) return false;
      captureMsOut = delay_ms;
      return true;
    }
    delay(100);
  }
  return false;
}

static bool waitAck(int cycleId, bool &sleepOut) {
  uint32_t t0 = ms();
  while (ms() - t0 < ACK_TOTAL_WAIT_MS) {
    esp_task_wdt_reset();
    String path = String("/waitack?deviceid=") + CAM_ID + "&cycle_id=" + String(cycleId);
    String req =
        String("GET ") + path + " HTTP/1.1\r\n" +
        "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
        "Connection: close\r\n\r\n";

    HttpResp r;
    if (!httpRequestRaw(req, r, 35000)) { delay(100); continue; }
    if (r.status != 200) { delay(100); continue; }

    bool s = false;
    if (!jsonFindBool(r.body, "sleep", s)) { delay(100); continue; }
    sleepOut = s;
    return true;
  }
  return false;
}

// ------------------- Resume Upload -------------------
static bool initUpload(int cycleId, size_t jpegSize, uint32_t jpegCrc, String &transferIdOut, int &resumeFromChunk) {
  int chunkCount = (jpegSize + CHUNK_SIZE - 1) / CHUNK_SIZE;

  String payload = String("{") +
    "\"cam_id\":\"" + CAM_ID + "\"," +
    "\"cycle_id\":" + String(cycleId) + "," +
    "\"jpeg_size\":" + String(jpegSize) + "," +
    "\"chunk_size\":" + String(CHUNK_SIZE) + "," +
    "\"chunk_count\":" + String(chunkCount) + "," +
    "\"jpeg_crc32\":\"" + String(jpegCrc, HEX) + "\"," +
    "\"rssi\":" + String(WiFi.RSSI()) +
    "}";

  String req =
      String("POST /upload/init HTTP/1.1\r\n") +
      "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
      "Connection: close\r\n" +
      "Content-Type: application/json\r\n" +
      "Content-Length: " + String(payload.length()) + "\r\n\r\n" +
      payload;

  HttpResp r;
  if (!httpRequestRaw(req, r, 12000)) return false;
  if (r.status != 200) return false;

  String tid;
  int resume = 0;
  if (!jsonFindString(r.body, "transfer_id", tid)) return false;
  jsonFindInt(r.body, "resume_from_chunk", resume);

  transferIdOut = tid;
  resumeFromChunk = resume;
  return true;
}

static bool uploadChunk(const String &transferId, int chunkIndex, const uint8_t *data, size_t len) {
  uint32_t chunkCrc = crc32(data, len);

  WiFiClient client;
  if (!client.connect(SERVER_HOST, SERVER_PORT)) return false;

  client.setTimeout(CHUNK_SOCK_TIMEOUT_MS);
  client.setNoDelay(true);

  String headers =
      String("POST /upload/chunk HTTP/1.1\r\n") +
      "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
      "Connection: close\r\n" +
      "X-Transfer-ID: " + transferId + "\r\n" +
      "X-Chunk-Index: " + String(chunkIndex) + "\r\n" +
      "X-Chunk-CRC32: " + String(chunkCrc, HEX) + "\r\n" +
      "Content-Type: application/octet-stream\r\n" +
      "Content-Length: " + String(len) + "\r\n\r\n";

  client.print(headers);

  size_t written = 0;
  size_t remaining = len;
  const uint8_t *ptr = data;

  while (remaining > 0) {
    size_t blk = (remaining > TCP_WRITE_BLOCK) ? TCP_WRITE_BLOCK : remaining;
    size_t w = client.write(ptr, blk);
    if (w == 0) break;
    written += w;
    ptr += w;
    remaining -= w;
  }

  if (written != len) {
    client.stop();
    return false;
  }

  String statusLine;
  if (!readLine(client, statusLine, 5000)) {
    client.stop();
    return false;
  }

  statusLine.trim();
  client.stop();

  return (statusLine.startsWith("HTTP/1.1 200") || statusLine.startsWith("HTTP/1.0 200"));
}

static bool finalizeUpload(const String &transferId) {
  String payload = String("{\"transfer_id\":\"") + transferId + "\"}";
  String req =
      String("POST /upload/finalize HTTP/1.1\r\n") +
      "Host: " + SERVER_HOST + ":" + String(SERVER_PORT) + "\r\n" +
      "Connection: close\r\n" +
      "Content-Type: application/json\r\n" +
      "Content-Length: " + String(payload.length()) + "\r\n\r\n" +
      payload;

  HttpResp r;
  if (!httpRequestRaw(req, r, 12000)) return false;
  return (r.status == 200);
}

static bool uploadImageResumable(camera_fb_t *fb, int cycleId) {
  if (!fb || !fb->buf || fb->len == 0) return false;

  uint32_t jpegCrc = crc32(fb->buf, fb->len);
  int chunkCount = (fb->len + CHUNK_SIZE - 1) / CHUNK_SIZE;

  Serial.printf("[UPLOAD] JPEG size=%u CRC=0x%08X chunks=%d\n", fb->len, jpegCrc, chunkCount);

  String transferId;
  int resumeFromChunk = 0;

  for (uint8_t attempt = 1; attempt <= UPLOAD_MAX_RETRIES; attempt++) {
    if (initUpload(cycleId, fb->len, jpegCrc, transferId, resumeFromChunk)) {
      Serial.printf("[UPLOAD] Init OK: transfer_id=%s resume_from=%d\n", transferId.c_str(), resumeFromChunk);
      break;
    }
    if (attempt == UPLOAD_MAX_RETRIES) return false;
    delay(500 * attempt);
  }

  uint32_t uploadStart = ms();
  for (int i = resumeFromChunk; i < chunkCount; i++) {
    esp_task_wdt_reset();

    size_t offset = (size_t)i * CHUNK_SIZE;
    size_t chunkLen = (offset + CHUNK_SIZE <= fb->len) ? CHUNK_SIZE : (fb->len - offset);

    bool chunkOk = false;
    for (uint8_t retry = 1; retry <= CHUNK_MAX_RETRIES; retry++) {
      if (uploadChunk(transferId, i, &fb->buf[offset], chunkLen)) {
        chunkOk = true;
        break;
      }
      Serial.printf("[WARN] Chunk %d retry %d\n", i, retry);
      delay(100 * retry);
    }

    if (!chunkOk) {
      Serial.printf("[ERR] Chunk %d failed after %d retries\n", i, CHUNK_MAX_RETRIES);
      return false;
    }

    if ((i % 10) == 0 || i == chunkCount - 1) {
      Serial.printf("[PROGRESS] %d/%d chunks (%.1f%%)\n", i + 1, chunkCount, ((i + 1) * 100.0) / chunkCount);
    }
  }

  uint32_t uploadMs = ms() - uploadStart;
  float rate = (fb->len * 1000.0f) / (uploadMs * 1024.0f);
  Serial.printf("[UPLOAD] Complete in %u ms (%.1f KB/s)\n", uploadMs, rate);

  for (uint8_t attempt = 1; attempt <= UPLOAD_MAX_RETRIES; attempt++) {
    if (finalizeUpload(transferId)) {
      Serial.println("[UPLOAD] Finalized OK");
      return true;
    }
    delay(500 * attempt);
  }

  return false;
}

// ------------------- Main -------------------
void setup() {
  Serial.begin(921600);
  delay(200);

  pinMode(LED_FLASH_GPIO, OUTPUT);
  digitalWrite(LED_FLASH_GPIO, LOW);
  pinMode(STATUS_LED_GPIO, OUTPUT);
  digitalWrite(STATUS_LED_GPIO, HIGH);

  esp_task_wdt_init(60, true);
  esp_task_wdt_add(NULL);

  blinkStatus(2, 120, 120);
  startCameraOV5640();

  uint32_t tBoot = ms();

  uint32_t t0 = ms();
  if (!connectWiFi(WIFI_TIMEOUT_MS)) goToSleep(FAIL_SLEEP_SEC);
  Serial.printf("[TIMING] wifi_connect=%u ms rssi=%d\n", (ms() - t0), WiFi.RSSI());

  // SNTP необязателен (не прерываем программу при неудаче)
  t0 = ms();
  bool timeOk = syncTimeSNTP();
  Serial.printf("[TIMING] sntp=%u ms ok=%s\n", (ms() - t0), timeOk ? "true" : "false");

  int cycleId = -1, captureDelayMs = -1;
  t0 = ms();
  if (!postHello(cycleId, captureDelayMs)) goToSleep(FAIL_SLEEP_SEC);
  Serial.printf("[TIMING] hello=%u ms cycle_id=%d capture_delay=%d\n", (ms() - t0), cycleId, captureDelayMs);

  int cmdCaptureDelayMs = -1;
  t0 = ms();
  if (!waitCmd(cycleId, cmdCaptureDelayMs)) goToSleep(FAIL_SLEEP_SEC);
  Serial.printf("[TIMING] waitcmd=%u ms capture_delay=%d\n", (ms() - t0), cmdCaptureDelayMs);

  // Синхронная съёмка
  int waitMs = cmdCaptureDelayMs;
  if (waitMs > 0 && waitMs < 10000) {
    Serial.printf("[SYNC] Waiting %d ms for synchronized capture\n", waitMs);
    delay((uint32_t)waitMs);
  }

  t0 = ms();
  camera_fb_t *fb = esp_camera_fb_get();
  uint32_t captureMs = ms() - t0;

  if (!fb) {
    Serial.println("[ERR] Capture FAILED");
    goToSleep(FAIL_SLEEP_SEC);
  }
  Serial.printf("[TIMING] capture=%u ms jpeg_bytes=%u\n", captureMs, fb->len);

  bool uploaded = uploadImageResumable(fb, cycleId);
  esp_camera_fb_return(fb);

  if (!uploaded) {
    Serial.println("[ERR] Upload FAILED");
    goToSleep(FAIL_SLEEP_SEC);
  }

  bool sleepFlag = false;
  t0 = ms();
  waitAck(cycleId, sleepFlag);
  Serial.printf("[TIMING] waitack=%u ms sleep=%s\n", (ms() - t0), sleepFlag ? "true" : "false");

  Serial.printf("[TIMING] total_awake=%u ms\n", (ms() - tBoot));
  digitalWrite(STATUS_LED_GPIO, HIGH);
  goToSleep(CAPTURE_PERIOD_SEC);
}

void loop() {}
