#!/usr/bin/env python3

import time
import subprocess
import json
import threading
import os
import socket
from datetime import datetime
from zoneinfo import ZoneInfo
from luma.oled.device import ssd1306
from luma.core.interface.serial import i2c
from PIL import Image, ImageDraw, ImageFont

I2C_PORT    = 1
I2C_ADDR    = 0x3C
GPS_PPS_SYS = "/sys/class/pps/pps0/assert"
RB_PPS_SYS  = "/sys/class/pps/pps1/assert"
LOCK_CHIP   = "0"
LOCK_LINE   = "22"
TZ_ZONE     = "America/Chicago"
STATUS_INTERVAL  = 2
SUBSECOND_DIGITS = 5
CHAR_SPACING     = 7
GPSD_HOST   = "127.0.0.1"
GPSD_PORT   = 2947

status = {
    "sats": "--",
    "gps_pps": "?",
    "rb_pps": "?",
    "rb_lock": False,
    "ip": "...",
    "source": "---",
    "offset": "---",
}

_last_pps = {}

def draw_satellite(draw, x, y):
    draw.line((x+6, y, x+6, y+2), fill=255)
    draw.point((x+5, y), fill=255)
    draw.point((x+7, y), fill=255)
    draw.rectangle((x+4, y+3, x+8, y+7), fill=255)
    draw.rectangle((x, y+3, x+2, y+7), fill=255, outline=255)
    draw.line((x+3, y+5, x+3, y+5), fill=255)
    draw.rectangle((x+10, y+3, x+12, y+7), fill=255, outline=255)
    draw.line((x+9, y+5, x+9, y+5), fill=255)
    draw.line((x, y+5, x+2, y+5), fill=0)
    draw.line((x+10, y+5, x+12, y+5), fill=0)

def draw_lock_closed(draw, x, y):
    draw.arc((x+1, y+1, x+5, y+5), 180, 0, fill=255)
    draw.line((x+1, y+3, x+1, y+4), fill=255)
    draw.line((x+5, y+3, x+5, y+4), fill=255)
    draw.rectangle((x, y+5, x+6, y+9), fill=255)
    draw.rectangle((x+2, y+6, x+4, y+8), fill=0)

def draw_lock_open(draw, x, y):
    draw.arc((x+1, y, x+5, y+4), 180, 0, fill=255)
    draw.line((x+1, y+2, x+1, y+4), fill=255)
    draw.rectangle((x, y+5, x+6, y+9), fill=255)
    draw.rectangle((x+2, y+6, x+4, y+8), fill=0)

def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "no network"

def gpsd_listener():
    buf = ""
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            sock.connect((GPSD_HOST, GPSD_PORT))
            sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
            buf = ""
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                buf += data.decode("utf-8", errors="replace")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if msg.get("class") != "SKY":
                        continue
                    sats = msg.get("satellites")
                    if sats is None:
                        continue
                    used = sum(1 for s in sats if s.get("used"))
                    if used > 0 or status["sats"] == "--":
                        status["sats"] = str(used)
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        time.sleep(2)

def check_pps(sys_path):
    if not os.path.exists(sys_path):
        return "FAIL"
    try:
        with open(sys_path, 'r') as f:
            current = f.read().strip()
        if not current:
            return "FAIL"
        prev = _last_pps.get(sys_path)
        _last_pps[sys_path] = current
        if prev is None:
            return "PASS"
        return "PASS" if current != prev else "FAIL"
    except Exception:
        return "FAIL"

def check_lock():
    try:
        out = subprocess.run(
            ["gpioget", "-c", LOCK_CHIP, LOCK_LINE],
            capture_output=True, text=True, timeout=2
        )
        return "inactive" in out.stdout
    except Exception:
        return False

def get_chrony_info():
    source = "---"
    offset = "---"
    try:
        out = subprocess.run(
            ["chronyc", "sources"],
            capture_output=True, text=True, timeout=3
        )
        for line in out.stdout.strip().split("\n"):
            line = line.strip()
            if len(line) < 2 or line[1] != '*':
                continue
            parts = line[2:].split()
            if len(parts) >= 6:
                refid = parts[0]
                off_val = parts[5]
                if refid in ("PPS", "RB"):
                    source = "Rb"
                elif refid in ("GPPS", "GPS", "SHM"):
                    source = "GPS"
                else:
                    source = "NTP"
                offset = off_val
                break
    except Exception:
        pass
    return source, offset

def format_offset(raw):
    if raw == "---":
        return raw
    raw = raw.strip().replace('[', '').replace(']', '')
    if raw and raw[0] == '+':
        raw = raw[1:]
    return raw

def status_updater():
    while True:
        try:
            status["gps_pps"] = check_pps(GPS_PPS_SYS)
        except Exception:
            pass
        try:
            status["rb_pps"] = check_pps(RB_PPS_SYS)
        except Exception:
            pass
        try:
            status["rb_lock"] = check_lock()
        except Exception:
            pass
        try:
            status["ip"] = get_ip()
        except Exception:
            pass
        try:
            src, off = get_chrony_info()
            status["source"] = src
            status["offset"] = off
        except Exception:
            pass
        time.sleep(STATUS_INTERVAL)

def draw_spaced(draw, x, y, text, font, spacing):
    for ch in text:
        if ch == ' ':
            x += 5
        elif ch in '.:':
            draw.text((x, y), ch, font=font, fill=255)
            x += 4 if ch == '.' else 5
            x += 4 if ch == '.' else 5
        else:
            draw.text((x, y), ch, font=font, fill=255)
            x += spacing

def main():
    serial = i2c(port=I2C_PORT, address=I2C_ADDR)
    device = ssd1306(serial)
    width = device.width
    height = device.height
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 9)
    except (IOError, OSError):
        font = ImageFont.load_default()
    tz = ZoneInfo(TZ_ZONE)
    status["ip"] = get_ip()

    gps_t = threading.Thread(target=gpsd_listener, daemon=True)
    gps_t.start()

    status_t = threading.Thread(target=status_updater, daemon=True)
    status_t.start()

    time.sleep(3)
    try:
        while True:
            image = Image.new('1', (width, height))
            draw = ImageDraw.Draw(image)

            draw_satellite(draw, 0, 0)
            draw.text((16, 0), status['sats'], font=font, fill=255)
            if status['rb_lock']:
                draw_lock_closed(draw, 30, 0)
            else:
                draw_lock_open(draw, 30, 0)
            draw.text((56, 0), f"Source:{status['source']}", font=font, fill=255)

            gps_ok = "PASS" if (status['gps_pps'] == "PASS" and status['sats'] not in ("--", "0")) else "FAIL"
            atomic_ok = "PASS" if (status['rb_pps'] == "PASS" and status['rb_lock']) else "FAIL"
            draw.text((0, 11), f"GPS:{gps_ok}", font=font, fill=255)
            draw.text((56, 11), f"Atomic:{atomic_ok}", font=font, fill=255)

            draw.line((0, 22, width, 22), fill=255)

            now = datetime.now(tz)
            us = now.strftime("%f")[:SUBSECOND_DIGITS]
            time_str = f"{now.strftime('%H:%M:%S')}.{us} {now.strftime('%Z')}"
            draw_spaced(draw, 0, 24, time_str, font, CHAR_SPACING)

            off_str = format_offset(status['offset'])
            draw.text((0, 37), status['ip'], font=font, fill=255)
            draw.text((85, 37), off_str, font=font, fill=255)

            draw.line((0, 48, width, 48), fill=255)

            date_str = now.strftime("%a, %b %d, %Y")
            draw.text((0, 51), date_str, font=font, fill=255)

            device.display(image)
            time.sleep(0.001)
    except KeyboardInterrupt:
        image = Image.new('1', (width, height))
        device.display(image)
        print("\nDisplay off.")

if __name__ == "__main__":
    main()
