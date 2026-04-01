#!/bin/bash

RED='\033[0;31m'
GRN='\033[0;32m'
YEL='\033[1;33m'
CYN='\033[0;36m'
RST='\033[0m'

pass() { echo -e "  ${GRN}[PASS]${RST} $1"; RESULTS+=("OK $1"); scroll "OK  $1"; }
fail() { echo -e "  ${RED}[FAIL]${RST} $1"; RESULTS+=("X  $1"); scroll "X   $1"; }
warn() { echo -e "  ${YEL}[WARN]${RST} $1"; RESULTS+=("?  $1"); scroll "?   $1"; }
info() { echo -e "  ${CYN}[INFO]${RST} $1"; }
section() { echo "--- $1 ---"; scroll "$1"; }

RESULTS=()
LED_PID=""
REAL_USER="${SUDO_USER:-$USER}"
SCROLL_LINES=()

scroll() {
    SCROLL_LINES+=("$(echo "$1" | cut -c1-21)")
    while [ ${#SCROLL_LINES[@]} -gt 3 ]; do
        SCROLL_LINES=("${SCROLL_LINES[@]:1}")
    done
    refresh_oled
    sleep 0.3
}

refresh_oled() {
    oled "DIAGNOSTICS" "---" "${SCROLL_LINES[@]}"
}

oled() {
    sudo -u "$REAL_USER" python3 - "$@" 2>/dev/null <<'PYEOF'
import sys
from luma.oled.device import ssd1306
from luma.core.interface.serial import i2c
from PIL import Image, ImageDraw, ImageFont

serial = i2c(port=1, address=0x3C)
device = ssd1306(serial)
device.cleanup = lambda *a, **k: None
font = ImageFont.load_default()
image = Image.new('1', (device.width, device.height))
draw = ImageDraw.Draw(image)

y = 0
for arg in sys.argv[1:]:
    if arg == '---':
        draw.line((0, y + 5, device.width, y + 5), fill=255)
        y += 11
    else:
        draw.text((0, y), arg, font=font, fill=255)
        y += 11
device.display(image)
PYEOF
}

oled_clear() {
    sudo -u "$REAL_USER" python3 - 2>/dev/null <<'PYEOF'
from luma.oled.device import ssd1306
from luma.core.interface.serial import i2c
from PIL import Image
serial = i2c(port=1, address=0x3C)
device = ssd1306(serial)
device.display(Image.new('1', (device.width, device.height)))
PYEOF
}

start_leds() {
    (
        while true; do
            gpioset -c 0 24=1 25=0 &>/dev/null &
            P=$!; sleep 0.5; kill $P 2>/dev/null; wait $P 2>/dev/null
            gpioset -c 0 24=0 25=1 &>/dev/null &
            P=$!; sleep 0.5; kill $P 2>/dev/null; wait $P 2>/dev/null
        done
    ) &
    LED_PID=$!
}

stop_leds() {
    [ -n "$LED_PID" ] && kill $LED_PID 2>/dev/null && wait $LED_PID 2>/dev/null
    killall gpioset 2>/dev/null
}

cleanup() {
    stop_leds
    oled_clear
    info "Restarting services..."
    systemctl start timeserver-display 2>/dev/null
    systemctl start timeserver-leds 2>/dev/null
}
trap cleanup EXIT

echo ""
echo "============================================"
echo "   TIME SERVER DIAGNOSTICS"
echo "============================================"
echo ""

info "Stopping services..."
systemctl stop timeserver-display 2>/dev/null
systemctl stop timeserver-leds 2>/dev/null
killall gpioset 2>/dev/null
sleep 1

start_leds
sleep 0.5

scroll "Starting tests..."
sleep 1
echo ""

section "[1/6] GPS Serial"
if command -v gpspipe &>/dev/null; then
    NMEA=$(timeout 5 gpspipe -r 2>/dev/null | grep '^\$' | head -3)
    if [ -n "$NMEA" ]; then
        pass "GPS Serial"
        echo "$NMEA" | while IFS= read -r line; do info "  ${line}"; done
    else
        fail "GPS Serial"
    fi
else
    fail "GPS Serial: gpspipe missing"
fi
echo ""

section "[2/6] GPS Sats"
sleep 3
SAT_COUNT=0
for attempt in 1 2 3; do
    SATS=$(timeout 10 gpspipe -w 2>/dev/null | while IFS= read -r line; do
        COUNT=$(echo "$line" | python3 -c "
import sys,json
try:
    m=json.loads(sys.stdin.read())
    if m.get('class')=='SKY' and 'satellites' in m:
        print(sum(1 for s in m['satellites'] if s.get('used')))
except: pass
" 2>/dev/null)
        if [ -n "$COUNT" ] && [ "$COUNT" -gt 0 ] 2>/dev/null; then
            echo "$COUNT"
            break
        fi
    done)
    if [ -n "$SATS" ] && [ "$SATS" -gt 0 ] 2>/dev/null; then
        SAT_COUNT=$SATS
        break
    fi
    sleep 1
done
if [ "$SAT_COUNT" -gt 0 ] 2>/dev/null; then
    pass "Satellites: ${SAT_COUNT}"
else
    fail "Satellites: 0"
fi
echo ""

section "[3/6] GPS PPS"
if [ -e /dev/pps0 ]; then
    COUNT=0
    while IFS= read -r line; do
        if echo "$line" | grep -q "assert"; then
            COUNT=$((COUNT + 1))
            [ "$COUNT" -ge 3 ] && break
        fi
    done < <(timeout 10 ppstest /dev/pps0 2>&1)
    [ "$COUNT" -ge 3 ] && pass "GPS PPS" || fail "GPS PPS"
else
    fail "GPS PPS: missing"
fi
echo ""

section "[4/6] Services"
systemctl is-active --quiet gpsd && pass "GPSD" || fail "GPSD"
systemctl is-active --quiet chrony && pass "Chrony" || fail "Chrony"
systemctl is-active --quiet ptp4l && pass "PTP" || warn "PTP: not running"
systemctl is-active --quiet phc2sys && pass "PHC2SYS" || warn "PHC2SYS: not running"
echo ""

section "[5/6] Atomic PPS"
if [ -e /dev/pps1 ]; then
    info "Listening (max 30s, any key to skip)..."
    GOT_PPS=0
    LAST_PPS=""
    SKIPPED=0
    for i in $(seq 1 30); do
        if [ -f /sys/class/pps/pps1/assert ]; then
            CURRENT=$(cat /sys/class/pps/pps1/assert 2>/dev/null)
            if [ -n "$CURRENT" ] && [ "$CURRENT" != "$LAST_PPS" ]; then
                GOT_PPS=$((GOT_PPS + 1))
                LAST_PPS="$CURRENT"
                info "  Pulse ${GOT_PPS}"
                [ "$GOT_PPS" -ge 3 ] && break
            fi
        fi
        read -t 1 -n 1 -s KEY 2>/dev/null && { SKIPPED=1; info "Skipped"; break; }
    done
    if [ "$GOT_PPS" -ge 3 ]; then
        pass "Atomic PPS"
    elif [ "$SKIPPED" -eq 1 ]; then
        warn "Atomic PPS: Skipped"
    else
        fail "Atomic PPS"
    fi
else
    fail "Atomic PPS: /dev/pps1 missing"
fi
echo ""

section "[6/6] Atomic Lock"
info "Checking (max 5 min, any key to skip)..."
info "NOTE: reads locked when Rb unpowered (pin floats low)"

LOCK_RAW=$(gpioget -c 0 22 2>/dev/null)
if echo "$LOCK_RAW" | grep -q "inactive"; then
    pass "Atomic Lock"
elif echo "$LOCK_RAW" | grep -q "active"; then
    warn "Unlocked - waiting..."
    LOCKED=0
    for i in $(seq 1 300); do
        VAL=$(gpioget -c 0 22 2>/dev/null)
        if echo "$VAL" | grep -q "inactive"; then
            LOCKED=1; break
        fi
        [ $((i % 30)) -eq 0 ] && info "Still unlocked... $((i/60))m $((i%60))s"
        read -t 1 -n 1 -s KEY 2>/dev/null && { info "Skipped"; break; }
    done
    [ "$LOCKED" -eq 1 ] && pass "Atomic Lock (${i}s)" || warn "Atomic Lock: timeout"
else
    fail "Atomic Lock: GPIO error"
fi
echo ""

echo "============================================"
echo "   RESULTS"
echo "============================================"
echo ""

SCROLL_LINES=()
scroll "COMPLETE"
sleep 1

for r in "${RESULTS[@]}"; do
    printf "  %s\n" "$r"
    scroll "$r"
    sleep 1.5
done
echo ""

echo "============================================"
echo "  Results on OLED - 30s (any key to exit)"
echo "============================================"
for i in $(seq 1 30); do
    read -t 1 -n 1 -s KEY 2>/dev/null && break
done
echo ""
