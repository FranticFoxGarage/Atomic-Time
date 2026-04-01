#!/bin/bash

SERVER="${1:-10.0.0.208}"
INTERVAL=10
LOG="ntp-bench-$(date +%Y%m%d-%H%M%S).log"
SAMPLES=0
SUM=0
MIN=999999
MAX=-999999
OVER_50=0
OVER_100=0
OVER_150=0
OVER_200=0
OVER_250=0
OVER_500=0
START=$(date +%s)
LAST_OFF="--"
LAST_DEL="--"
STATUS="Starting..."

cleanup() {
    END=$(date +%s)
    ELAPSED=$((END - START))
    HRS=$((ELAPSED / 3600))
    MINS=$(((ELAPSED % 3600) / 60))
    SECS=$((ELAPSED % 60))
    if [ "$SAMPLES" -gt 0 ]; then
        AVG=$(echo "scale=1; $SUM / $SAMPLES" | bc)
	PCT50=$(echo "scale=1; $OVER_50 * 100 / $SAMPLES" | bc)
        PCT100=$(echo "scale=1; $OVER_100 * 100 / $SAMPLES" | bc)
	PCT150=$(echo "scale=1; $OVER_150 * 100 / $SAMPLES" | bc)
	PCT200=$(echo "scale=1; $OVER_200 * 100 / $SAMPLES" | bc)
        PCT250=$(echo "scale=1; $OVER_250 * 100 / $SAMPLES" | bc)
        PCT500=$(echo "scale=1; $OVER_500 * 100 / $SAMPLES" | bc)
    else
        AVG="0"; PCT50="0"; PCT100="0"; PCT150="0"; PCT200="0"; PCT250="0"; PCT500="0"
    fi
    echo ""
    echo ""
    echo "  FINAL REPORT saved to $LOG"
    echo ""
    {
        echo "=========================================="
        echo "  FINAL REPORT"
        echo "  Server:       $SERVER"
        echo "  Duration:     ${HRS}h ${MINS}m ${SECS}s"
        echo "  Samples:      $SAMPLES"
        echo "  Avg offset:   ${AVG}us"
        echo "  Min offset:   ${MIN}us"
        echo "  Max offset:   ${MAX}us"
        echo "  Over 50us:    $OVER_50 (${PCT50}%)"
        echo "  Over 100us:   $OVER_100 (${PCT100}%)"
	echo "  Over 150us:   $OVER_150 (${PCT150}%)"
	echo "  Over 200us:   $OVER_200 (${PCT200}%)"
        echo "  Over 250us:   $OVER_250 (${PCT250}%)"
        echo "  Over 500us:   $OVER_500 (${PCT500}%)"
        echo "=========================================="
    } >> "$LOG"
    exit 0
}
trap cleanup INT TERM

draw() {
    END=$(date +%s)
    ELAPSED=$((END - START))
    HRS=$((ELAPSED / 3600))
    MINS=$(((ELAPSED % 3600) / 60))
    SECS=$((ELAPSED % 60))
    if [ "$SAMPLES" -gt 0 ]; then
        AVG=$(echo "scale=1; $SUM / $SAMPLES" | bc)
	PCT50=$(echo "scale=1; $OVER_50 * 100 / $SAMPLES" | bc)
        PCT100=$(echo "scale=1; $OVER_100 * 100 / $SAMPLES" | bc)
	PCT150=$(echo "scale=1; $OVER_150 * 100 / $SAMPLES" | bc)
	PCT200=$(echo "scale=1; $OVER_200 * 100 / $SAMPLES" | bc)
        PCT250=$(echo "scale=1; $OVER_250 * 100 / $SAMPLES" | bc)
        PCT500=$(echo "scale=1; $OVER_500 * 100 / $SAMPLES" | bc)
    else
        AVG="--"; PCT50="0"; PCT100="0"; PCT150="0"; PCT200="0"; PCT250="0"; PCT500="0"
    fi

    printf "\033[2J\033[H"
    echo ""
    echo "  ==========================================="
    echo "   NTP BENCHMARK - LIVE"
    echo "  ==========================================="
    echo ""
    echo "   Server:        $SERVER"
    echo "   Duration:      ${HRS}h ${MINS}m ${SECS}s"
    echo "   Samples:       $SAMPLES"
    echo "   Status:        $STATUS"
    echo ""
    echo "  -------------------------------------------"
    echo "   LAST SAMPLE"
    echo "  -------------------------------------------"
    echo "   Offset:        ${LAST_OFF}us"
    echo "   Delay:         ${LAST_DEL}us"
    echo ""
    echo "  -------------------------------------------"
    echo "   STATISTICS"
    echo "  -------------------------------------------"
    echo "   Avg offset:    ${AVG}us"
    echo "   Min offset:    ${MIN}us"
    echo "   Max offset:    ${MAX}us"
    echo ""
    echo "  -------------------------------------------"
    echo "   THRESHOLD VIOLATIONS"
    echo "  -------------------------------------------"
    echo "   Over 50us:     $OVER_50 (${PCT50}%)"
    echo "   Over 100us:    $OVER_100 (${PCT100}%)"
    echo "   Over 150us:    $OVER_150 (${PCT150}%)"
    echo "   Over 200us:    $OVER_200 (${PCT200}%)"
    echo "   Over 250us:    $OVER_250 (${PCT250}%)"
    echo "   Over 500us:    $OVER_500 (${PCT500}%)"
    echo ""
    echo "  ==========================================="
    echo "   Next sample in ${INTERVAL}s - Ctrl+C to stop"
    echo "  ==========================================="
}

draw

while true; do
    STATUS="Sampling..."
    draw

    RAW=$(ntpdate -q "$SERVER" 2>&1 | tail -1)
    OFFSET=$(echo "$RAW" | grep -oP '[-+]?[0-9]+\.[0-9]+ \+/-' | awk '{print $1}')
    DELAY=$(echo "$RAW" | grep -oP '\+/- [0-9]+\.[0-9]+' | awk '{print $2}')

    if [ -z "$OFFSET" ]; then
        STATUS="No response"
        draw
        sleep "$INTERVAL"
        continue
    fi

    ABS_US=$(echo "$OFFSET" | awk '{v=$1; if(v<0)v=-v; printf "%.1f", v*1000000}')
    LAST_OFF=$(echo "$OFFSET" | awk '{printf "%+.1f", $1*1000000}')
    LAST_DEL=$(echo "$DELAY" | awk '{printf "%.1f", $1*1000000}')
    SAMPLES=$((SAMPLES + 1))
    SUM=$(echo "$SUM + $ABS_US" | bc)

    GT=$(echo "$ABS_US > $MAX" | bc -l 2>/dev/null)
    [ "$GT" = "1" ] && MAX="$ABS_US"
    LT=$(echo "$ABS_US < $MIN" | bc -l 2>/dev/null)
    [ "$LT" = "1" ] && MIN="$ABS_US"

    [ "$(echo "$ABS_US > 50" | bc -l)" = "1" ] && OVER_50=$((OVER_50 + 1))
    [ "$(echo "$ABS_US > 100" | bc -l)" = "1" ] && OVER_100=$((OVER_100 + 1))
    [ "$(echo "$ABS_US > 150" | bc -l)" = "1" ] && OVER_150=$((OVER_150 + 1))
    [ "$(echo "$ABS_US > 200" | bc -l)" = "1" ] && OVER_200=$((OVER_200 + 1))
    [ "$(echo "$ABS_US > 250" | bc -l)" = "1" ] && OVER_250=$((OVER_250 + 1))
    [ "$(echo "$ABS_US > 500" | bc -l)" = "1" ] && OVER_500=$((OVER_500 + 1))

    echo "$(date +%H:%M:%S) ${LAST_OFF}us ${LAST_DEL}us" >> "$LOG"

    STATUS="Waiting..."
    draw
    sleep "$INTERVAL"
done
