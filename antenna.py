#!/usr/bin/env python3

import socket
import json
import sys

GPSD_HOST = "127.0.0.1"
GPSD_PORT = 2947

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((GPSD_HOST, GPSD_PORT))
    sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
    buf = ""
    print("Antenna positioning tool - Ctrl+C to quit")
    print()
    try:
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
                if not sats:
                    continue
                used = [s for s in sats if s.get("used")]
                unused = [s for s in sats if not s.get("used")]
                used_snr = [s.get("ss", 0) for s in used if s.get("ss", 0) > 0]
                all_snr = [s.get("ss", 0) for s in sats if s.get("ss", 0) > 0]
                avg_used = sum(used_snr) / len(used_snr) if used_snr else 0
                avg_all = sum(all_snr) / len(all_snr) if all_snr else 0

                print(f"\033[2J\033[H", end="")
                print(f"  USED: {len(used):>2}    VISIBLE: {len(sats):>2}    AVG SNR (used): {avg_used:.0f} dB")
                print()
                print(f"  {'PRN':>4}  {'AZ':>4}  {'EL':>3}  {'SNR':>4}  {'USED':>4}  SIGNAL")
                print(f"  {'----':>4}  {'----':>4}  {'---':>3}  {'----':>4}  {'----':>4}  {'------'}")

                for s in sorted(sats, key=lambda x: x.get("ss", 0), reverse=True):
                    prn = s.get("PRN", s.get("prn", "?"))
                    az = s.get("az", 0)
                    el = s.get("el", 0)
                    ss = s.get("ss", 0)
                    u = "*" if s.get("used") else ""
                    bars = int(ss / 5)
                    bar_str = "|" * bars
                    if ss >= 35:
                        color = "\033[32m"
                    elif ss >= 20:
                        color = "\033[33m"
                    else:
                        color = "\033[31m"
                    rst = "\033[0m"
                    print(f"  {prn:>4}  {az:>4}  {el:>3}  {ss:>4.0f}  {u:>4}  {color}{bar_str}{rst}")

                print()
                print(f"  GREEN=35+ dB  YELLOW=20-34 dB  RED=<20 dB")
    except KeyboardInterrupt:
        print("\nDone.")
    finally:
        sock.close()

if __name__ == "__main__":
    main()
