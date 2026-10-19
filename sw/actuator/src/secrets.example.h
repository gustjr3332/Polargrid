#pragma once
// Copy to secrets.h (git-ignored) and fill in. Without secrets.h the build uses these placeholders and Wi-Fi never connects.
#define WIFI_SSID "your-ssid"
#define WIFI_PASS "your-password"
#define CSE_HOST "http://192.168.0.10:3001"   // the MN-CSE as the ESP32 sees it (WSL needs mirrored networking or a port proxy)
#define CSE_NAME "TinyIoT-mn001"
#define RUN_ID "real1"                         // resource names and originators: {run}p0, C{run}p0, C{run}env
#define CELL_INDEX 0
#define CELL_ROW 0                             // where this cell sits in the window, seen from inside: row 0 = top
#define CELL_COL 0                             // col 0 = left. The app draws each new cell at this place
