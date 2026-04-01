#!/usr/bin/env python3

import time
import sys
import os
import subprocess

GPS_PPS_SYS = "/sys/class/pps/pps0/assert"
RB_PPS_SYS  = "/sys/class/pps/pps1/assert"
CHRONY_CONF = "/etc/chrony/chrony.conf"
LOCK_CHIP   = "0"
LOCK_LINE   = "22"

LOCK_HOLD_SECONDS = 60
LOCK_TIMEOUT      = 900
PPS_TIMEOUT       = 30
OFFSET_SAMPLES    = 10
SAMPLE_INTERVAL   = 2

def check_lock():
    try:
        out = subprocess.run(
            ["gpioget", "-c", LOCK_CHIP, LOCK_LINE],
            capture_output=True, text=True, timeout=2
        )
        return "inactive" in out.stdout
    except Exception:
        return False

def get_pps_seq(path):
    try:
        with open(path, 'r') as f:
            raw = f.read().strip()
        return int(raw.split('#')[1])
    except Exception:
        return -1

def read_pps_ts(path):
    with open(path, 'r') as f:
        raw = f.read().strip()
    ts_str = raw.split('#')[0]
    sec, nsec = ts_str.split('.')
    return int(sec) + int(nsec) / 1e9

def pps_active(path):
    seq1 = get_pps_seq(path)
    time.sleep(2)
    seq2 = get_pps_seq(path)
    return seq2 > seq1

def wait_for_lock():
    print("Waiting for Rb lock...", flush=True)
    start = time.monotonic()
    locked_since = None
    while time.monotonic() - start < LOCK_TIMEOUT:
        if check_lock():
            if locked_since is None:
                locked_since = time.monotonic()
                print(f"  Lock detected, confirming for {LOCK_HOLD_SECONDS}s...", flush=True)
            held = time.monotonic() - locked_since
            if held >= LOCK_HOLD_SECONDS:
                print(f"  Lock held for {LOCK_HOLD_SECONDS}s, confirmed.", flush=True)
                return True
        else:
            if locked_since is not None:
                print("  Lock dropped, restarting hold timer.", flush=True)
            locked_since = None
        time.sleep(1)
    print(f"  No stable lock after {LOCK_TIMEOUT}s, giving up.", flush=True)
    return False

def wait_for_pps(path, name):
    print(f"Checking {name} PPS...", flush=True)
    if not os.path.exists(path):
        print(f"  {path} not present.", flush=True)
        return False
    start = time.monotonic()
    while time.monotonic() - start < PPS_TIMEOUT:
        if pps_active(path):
            print(f"  {name} PPS active.", flush=True)
            return True
        time.sleep(1)
    print(f"  No {name} PPS pulses detected.", flush=True)
    return False

def measure_offset():
    print(f"Measuring offset ({OFFSET_SAMPLES} samples)...", flush=True)
    offsets = []
    for i in range(OFFSET_SAMPLES):
        gps_ts = read_pps_ts(GPS_PPS_SYS)
        rb_ts = read_pps_ts(RB_PPS_SYS)
        diff = rb_ts - gps_ts
        if diff > 0.5:
            diff -= 1.0
        elif diff < -0.5:
            diff += 1.0
        offsets.append(diff)
        print(f"  [{i+1}/{OFFSET_SAMPLES}] {diff*1000:.1f}ms", flush=True)
        if i < OFFSET_SAMPLES - 1:
            time.sleep(SAMPLE_INTERVAL)
    avg = sum(offsets) / len(offsets)
    spread = max(offsets) - min(offsets)
    print(f"  Average: {avg*1000:.1f}ms  Spread: {spread*1000:.2f}ms", flush=True)
    if spread > 0.01:
        print(f"  WARNING: spread is large, offset may be unreliable.", flush=True)
    return avg

def update_chrony(offset):
    print("Updating chrony.conf...", flush=True)
    with open(CHRONY_CONF, 'r') as f:
        lines = f.readlines()
    new_lines = []
    found = False
    for line in lines:
        if 'refid RB' in line:
            found = True
            base = line.split('offset')[0].rstrip()
            new_line = f"{base} offset {offset:.6f}\n"
            new_lines.append(new_line)
            print(f"  {new_line.strip()}", flush=True)
        else:
            new_lines.append(line)
    if not found:
        print("  No 'refid RB' line found in chrony.conf", flush=True)
        return False
    with open(CHRONY_CONF, 'w') as f:
        f.writelines(new_lines)
    return True

def main():
    print("=== Rb PPS Offset Calibration ===", flush=True)
    print("", flush=True)

    if not wait_for_lock():
        print("Exiting, chrony will use GPS only.", flush=True)
        sys.exit(0)

    if not wait_for_pps(GPS_PPS_SYS, "GPS"):
        print("Exiting, no GPS reference to calibrate against.", flush=True)
        sys.exit(0)

    if not wait_for_pps(RB_PPS_SYS, "Rb"):
        print("Exiting, Rb locked but no PPS signal.", flush=True)
        sys.exit(0)

    print("", flush=True)
    offset = measure_offset()

    print("", flush=True)
    if not update_chrony(offset):
        sys.exit(1)

    print("Restarting chrony...", flush=True)
    subprocess.run(["systemctl", "restart", "chrony"], check=True)

    print("", flush=True)
    print(f"Calibration complete. Offset: {offset*1000:.1f}ms", flush=True)

if __name__ == "__main__":
    main()
