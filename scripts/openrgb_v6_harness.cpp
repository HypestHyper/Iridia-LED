// Ground truth for tests/test_sdk_client.py: OpenRGB's own protocol 6 encoder and parser.
//
// Build against an OpenRGB source tree (release_1.0 or newer), from a folder holding:
//   RGBController.cpp/.h, RGBControllerInterface.h, StringUtils.cpp/.h (from OpenRGB),
//   nlohmann/json.hpp (OpenRGB's dependencies/json), and a LogManager.h stub:
//     #pragma once
//     #define LOG_FATAL(...)   (and LOG_ERROR, LOG_WARNING, LOG_INFO, LOG_VERBOSE, LOG_DEBUG,
//                               LOG_TRACE, LOG_DIALOG the same way)
//     #include <nlohmann/json.hpp>
//     using json = nlohmann::json;
//   g++ -std=c++17 -I. -o harness openrgb_v6_harness.cpp RGBController.cpp StringUtils.cpp -lpthread
//
//   ./harness device > tests/data/openrgb1.0-device-v6.bin   a test device, as OpenRGB writes it
//   ./harness parse-device < description                    what OpenRGB reads from a description
//   ./harness mode < mode-description                       what OpenRGB reads from a mode
#include <sstream>
#include <any>
#include <iostream>
#include <fstream>
#include <iterator>
#include <mutex>
#include <shared_mutex>
#include <thread>
#include <condition_variable>
#include <atomic>
#include <nlohmann/json.hpp>
#define protected public
#define private public
#include "RGBController.h"
#undef protected
#undef private
#include <cstdio>
#include <fstream>
#include <iterator>

static mode mk_mode(const char* name, unsigned flags, unsigned color_mode, unsigned ncol) {
    mode m; m.name = name; m.value = 7; m.flags = flags;
    m.speed_min = 1; m.speed_max = 5; m.brightness_min = 0; m.brightness_max = 100;
    m.colors_min = ncol ? 1 : 0; m.colors_max = ncol; m.speed = 3; m.brightness = 100; m.direction = 0;
    m.color_mode = color_mode; m.colors.assign(ncol, 0x00336699);
    return m;
}

int main(int argc, char** argv) {
    std::string what = argc > 1 ? argv[1] : "device";
    if (what == "device") {
        RGBController c;
        c.name = "Test ARGB Controller"; c.vendor = "Tester"; c.description = "a test";
        c.version = "1.0"; c.serial = "S1"; c.location = "HID: /dev/hidraw9"; c.type = 4;
        c.display_name = "My Controller"; c.configuration = "{\"a\":1}"; c.flags = 3;
        c.modes.push_back(mk_mode("Direct", 0x20, 1, 0));
        c.modes.push_back(mk_mode("Static", 0x40 | 0x10, 2, 1));
        c.active_mode = 1;
        const char* zn[2] = {"Channel 1", "Channel 2"};
        unsigned counts[2] = {3, 2};
        unsigned start = 0;
        for (int i = 0; i < 2; i++) {
            zone z; z.name = zn[i]; z.display_name = i ? "Shelf" : ""; z.type = 1; z.start_idx = start;
            z.leds_count = counts[i]; z.leds_min = 0; z.leds_max = 80; z.flags = i ? 1 : 0; z.active_mode = -1;
            if (i == 1) {
                z.matrix_map.height = 1; z.matrix_map.width = 2; z.matrix_map.map = {0, 1};
                segment s; s.name = "Seg A"; s.type = 1; s.start_idx = 0; s.leds_count = 2; s.flags = 0;
                s.matrix_map.height = 1; s.matrix_map.width = 2; s.matrix_map.map = {1, 0};
                z.segments.push_back(s);
                z.modes.push_back(mk_mode("Zone Rainbow", 1, 0, 0));
            }
            c.zones.push_back(z);
            for (unsigned k = 0; k < counts[i]; k++) {
                led l; l.name = std::string(zn[i]) + " LED " + std::to_string(k + 1); l.value = k;
                c.leds.push_back(l);
            }
            start += counts[i];
        }
        c.led_display_names = {};
        c.SetupColors();
        for (unsigned k = 0; k < c.colors.size(); k++) c.colors[k] = 0x00010203 + k;   // r=3+k? little endian: R=0x03+k, G=0x02, B=0x01
        unsigned size = RGBController::GetDeviceDescriptionSize(&c, 6);
        std::vector<unsigned char> buf(size);
        unsigned char* end = RGBController::GetDeviceDescriptionData(buf.data(), &c, 6);
        fprintf(stderr, "size %u written %ld\n", size, (long)(end - buf.data()));
        fwrite(buf.data(), 1, size, stdout);
    } else if (what == "parse-device") {    // a device description on stdin -> summary
        std::vector<unsigned char> in((std::istreambuf_iterator<char>(std::cin)), {});
        RGBController c;
        unsigned char* p = RGBController::SetDeviceDescription(in.data(), in.size(), &c, 6);
        if (!p) { printf("PARSE FAILED\n"); return 1; }
        printf("used %ld of %zu: type=%d name=%s vendor=%s loc=%s active=%d modes=%zu", (long)(p - in.data()), in.size(),
               c.type, c.name.c_str(), c.vendor.c_str(), c.location.c_str(), c.active_mode, c.modes.size());
        for (auto& m : c.modes) printf(" [%s cm=%u ncol=%zu]", m.name.c_str(), m.color_mode, m.colors.size());
        printf(" zones:");
        for (auto& z : c.zones) printf(" [%s n=%u min=%u max=%u]", z.name.c_str(), z.leds_count, z.leds_min, z.leds_max);
        printf(" leds=%zu colors=%zu\n", c.leds.size(), c.colors.size());
    } else if (what == "mode") {        // parse a mode description from stdin, print its fields
        std::vector<unsigned char> in((std::istreambuf_iterator<char>(std::cin)), {});
        mode m;
        unsigned char* p = RGBController::SetModeDescription(in.data(), in.size(), &m, 6);
        if (!p) { printf("PARSE FAILED\n"); return 1; }
        printf("used %ld of %zu\nname=%s flags=%u speed=%u-%u bright=%u-%u colors=%u-%u speed=%u brightness=%u dir=%u color_mode=%u ncolors=%zu",
               (long)(p - in.data()), in.size(), m.name.c_str(), m.flags, m.speed_min, m.speed_max, m.brightness_min,
               m.brightness_max, m.colors_min, m.colors_max, m.speed, m.brightness, m.direction, m.color_mode, m.colors.size());
        for (auto col : m.colors) printf(" %06x", col);
        printf("\n");
    }
    return 0;
}
