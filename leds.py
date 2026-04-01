#!/usr/bin/env python3

import subprocess
import time
import os
import sys
import json
import socket
import threading

CHIP        = "0"
RED_LINE    = "24"
YELLOW_LINE = "25"
LOCK_LINE   = "22"

GPS_PPS_SYS = "/sys/class/pps/pps0/assert"
RB_PPS_SYS  = "/sys/class/pps/pps1/assert"
GPSD_HOST   = "127.0.0.1"
GPSD_PORT   = 2947

_last_pps = {}
_led_procs = {}

status = {
    "locked": False,
    "gps_ok": False,
    "rb_ok": False,
    "sats_ok": False,
}

def set_led(line, state):
    key = line
    if key in _led_procs:
        try:
            _led_procs[key].kill()
            _led_procs[key].wait()
        except Exception:
            pass
    val = "1" if state else "0"
    _led_procs[key] = subprocess.Popen(
        ["gpioset", "-c", CHIP, f"{line}={val}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def kill_all():
    for k in list(_led_procs):
        try:
            _led_procs[k].kill()
            _led_procs[k].wait()
        except Exception:
            pass

def check_lock():
    try:
        out = subprocess.run(
            ["gpioget", "-c", CHIP, LOCK_LINE],
            capture_output=True, text=True, timeout=2
        )
        return "inactive" in out.stdout
    except Exception:
        return False

def check_pps(sys_path):
    if not os.path.exists(sys_path):
        return False
    try:
        with open(sys_path, 'r') as f:
            current = f.read().strip()
        if not current:
            return False
        prev = _last_pps.get(sys_path)
        _last_pps[sys_path] = current
        if prev is None:
            return True
        return current != prev
    except Exception:
        return False

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
                    if used > 0:
                        status["sats_ok"] = True
                    elif status["sats_ok"]:
                        status["sats_ok"] = False
        except Exception:
            pass
        try:
            sock.close()
        except Exception:
            pass
        time.sleep(2)

def status_updater():
    while True:
        try:
            status["locked"] = check_lock()
        except Exception:
            pass
        try:
            status["gps_ok"] = check_pps(GPS_PPS_SYS)
        except Exception:
            pass
        try:
            status["rb_ok"] = check_pps(RB_PPS_SYS)
        except Exception:
            pass
        time.sleep(2)

def main():
    set_led(RED_LINE, True)
    set_led(YELLOW_LINE, True)
    time.sleep(5)

    gps_t = threading.Thread(target=gpsd_listener, daemon=True)
    gps_t.start()

    t = threading.Thread(target=status_updater, daemon=True)
    t.start()
    time.sleep(3)

    last_red = None
    last_yellow = None

    try:
        while True:
            locked = status["locked"]
            if locked != last_red:
                set_led(RED_LINE, not locked)
                last_red = locked

            has_error = (
                not status["locked"]
                or not status["gps_ok"]
                or not status["rb_ok"]
                or not status["sats_ok"]
            )

            if has_error:
                want_on = time.time() % 1.0 < 0.5
                if want_on != last_yellow:
                    set_led(YELLOW_LINE, want_on)
                    last_yellow = want_on
            else:
                if last_yellow is not False:
                    set_led(YELLOW_LINE, False)
                    last_yellow = False

            time.sleep(0.05)

    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        kill_all()

if __name__ == "__main__":
    main()
