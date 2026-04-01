AI DISCLAIMER: A large portion of the code in this repo was written with the help of an LLM.

# WHAT?

Its a DIY stratum-1 time server built around a Raspberry Pi CM4, u-blox NEO-7M GPS receiver, and an FEI FE-5680A rubidium oscillator. Serves NTP to a local network from a 1U rackmount chassis with a green OLED display and LED status indicators.

## Why did you make this?

Atomic clock cool.

## What it do tho?

GPS provides a UTC time reference via NMEA sentences and a 1Hz/PPS (pulse per second) signal. The rubidium oscillator provides a second, much more stable 1PPS signal. chrony compares both PPS sources and serves the best one to NTP clients.

The OLED display shows satellite count, lock status, the active chrony source, GPS and atomic clock health, current time, IP address, chrony offset, and date. Three LEDs on the front panel show power, rubidium lock status, and yellow when anything is wrong (low sat count, PPS missing, etc..).

## Hardware

| Part | Details |
|------|---------|
| Compute | Raspberry Pi CM4 on Waveshare CM4-NANO-B carrier board |
| GPS | HiLetgo NEO-7M, UART at 9600 baud, PPS on GPIO18 (/dev/pps0) |
| GPS Antenna | External active antenna via SMA (ceramic patch antenna physically removed from the NEO-7M board) |
| Atomic clock | FEI FE-5680A rubidium oscillator, Option 01 variant. 10MHz sine out on SMA. Lock signal on DB-9 pin 3 |
| Frequency divider | eBay board converts 10MHz to 1Hz for PPS on GPIO27 (/dev/pps1) |
| RF transformer | 18:6 flux-coupled RF transformer between Rb SMA and divider input, steps up ~1.4Vpp to ~4.2Vpp (divider board needs +10dBm minimum) |
| Display | 2.42" SSD1309 128x64 green OLED, I2C at 0x3C |
| Chassis | Generic 1U rackmount off eBay, front panel cut for display|
| LEDs | Green (3.3V, always on), Red on GPIO24 (on = Rb unlocked), Yellow on GPIO25 (1Hz flash on error) |

The FE-5680a runs direct from the 15V/3A power supply. The CM4 is powered through the GPIO header via a converter to bring the 15v down to 5v - havnt messured the amp draw but its fine probobly. The rubidium unit draws about 2A at cold start and settles to around 180mA once warm. It takes roughly 5-15 minutes to achieve physics lock after power-on from a cold start.

## Wiring

Pin numbers refer to the CM4-NANO-B 40-pin GPIO header on the waveshare board I used, may be universal to pi's but didnt check, just went off the waveshare pdf

| Pin | GPIO | Function | Device |
|-----|------|----------|--------|
| 1 | 3.3V | Power | OLED VDD |
| 2 | 5V | Power | GPS VCC, CM4 power in |
| 3 | GPIO2 (SDA) | I2C data | OLED SDA |
| 5 | GPIO3 (SCL) | I2C clock | OLED SCL |
| 6 | GND | Ground | To ground bus, shared across everything |
| 8 | GPIO14 (TXD) | UART TX | GPS RXD |
| 9 | GND | Ground | OLED GND |
| 10 | GPIO15 (RXD) | UART RX | GPS TXD |
| 12 | GPIO18 | PPS input | GPS PPS (/dev/pps0) |
| 13 | GPIO27 | PPS input | Rb PPS via divider (/dev/pps1) |
| 14 | GND | Ground | FE-5680A GND |
| 15 | GPIO22 | Digital input | FE-5680A LOCK (through voltage divider) |
| 17 | 3.3V | Power | Green LED (always on) |
| 18 | GPIO24 | Digital output | Red LED (330 ohm to GND) |
| 22 | GPIO25 | Digital output | Yellow LED (330 ohm to GND) |

A reset button can be wired between the RUN pad on the CM4 and GND, I tried this at first but was worried the pads would get ripped off the second i forgot those were soldered to something so small so just ditched it.

### FE-5680A DB-9 Pinout

Pin 1 is +15V input. Pin 2 is GND. Pin 3 is the lock indicator (>3V when unlocked, <1V when locked, imo really dumb since it looks locked when its powered off). Pin 6 is listed as "NOT USED" despite some documentation suggesting it carries PPS...It does not on mine. The 10MHz output is on the SMA jack (J2).

### Voltage dividers

The lock signal on DB-9 pin 3 swings between roughly 0V and 5V. A 100k + 100k resistive divider brings the high side down to about 2.5V so it dosent slam the GPIO22 with 5v.

The frequency divider board outputs a 5Vpp square wave. A 1k (series) + 1.5k (to ground) divider brings that down to about 3.0V for GPIO27 again so we arnt slamming the Pi with 5v.

## Timing chain

Trust me Its actually a *REALLY* accurate clock but the CM4 and Network delays are the weakest link.

The NEO-7M receives GPS satellite signals and produces two outputs: NMEA sentences over UART (coarse time, accurate to maybe 100-200ms by the time gpsd parses them) and a PPS pulse on GPIO18 (accurate to about 30-50ns relative to UTC). The NMEA data tells chrony what second it is. The PPS pulse tells chrony exactly when that second starts. Neither is useful without the other, which is why the chrony config has `lock GPS` on both PPS refclocks. I plan to upgrade to a NEO-M9N because I already bought it due to having zero impulse control.

The FE-5680a's internal rubidium physics package generates a 10MHz signal that is stable to roughly 1-5 parts per 10^11 per day...something something a second or so off a year. The external frequency divider board counts 10 million cycles and outputs one pulse, giving a 1PPS signal. This PPS has significantly lower jitterr than the GPS PPS (roughly 1-5ns vs 30-50ns). chrony is configured with `prefer` on the Rb PPS, so when both sources are healthy, the rubidium is what actually gets served to NTP clients. The GPS PPS carries `trust`, which keeps the rubidium aligned to UTC over longer timescales.

As I already mentioned the primary weakest link in the chain is the CM4's GPIO interrupt timestamping. The kernel has to notice the PPS edge, then timestamp it, then hand that timestamp to chrony. In a my general-purpose Linux kernel with other things going on, like running scripts for silly lights and display, this adds 1-10 microseconds of jitter. The little bit of kernel tuning i have attemtped helps keep this closer to 1-2 microseconds ...I think - I dont have a solid way of mesuring this right now.

For NTP clients on the LAN, ive been seeing about 0.4ms offset from UTC (measured with `ntpdate -q`), dominated by network latency rather than the clock source itself.

### GPS failover

chrony falls back to the rubidium PPS as the sole timing source. The Rb oscillator drifts about 1 microsecond per day without GPS correction, so for NTP purposes, you could lose GPS for weeks and still be well within tolerance. When GPS returns, chrony re-disciplines the Rb PPS against it.

### Atomic clock failover

chrony uses GPS PPS directly. Not as good as Rb obviously but setup this way so Im not freaking out come the day my precious Rb source runs out of life and i dont have a time server after pointing all my stuff at it.

### Both Fail???

Just uses NTP from the debian time server pool. This is also what it does at boot while the Rb source gets warmed up and GPS proves its self worthy to chrony.

### Files in this repo

`display.py` drives the OLED screen. It keeps a persistent socket open to gpsd for satellite count. PPS status comes from sysfs, lock state from gpioget, chrony info from chronyc. Redraws roughly every millisecond. GPS shows PASS when PPS is active and sats > 0. Atomic shows PASS when PPS is active and a Lock icon when the Rb has lock.

`leds.py` drives the front panel LEDs. Same persistent gpsd socket thing as display.py for satellite data. Checks lock/PPS/sats every 2 seconds in background threads. The main loop runs at 50ms and syncs the yellow 1Hz flash to the system clock (`time.time() % 1.0 < 0.5`). Red is on when Rb is unlocked..and powered on since locked = low. The gpioset subprocesses have to stay alive because libgpiod v2 releases the pin when the process exits, so each LED has a persistent Popen. Both LEDs turn on for 5 seconds at startup as a test.

`diag.sh` stops display and LED services, flashes red/yellow alternating during testing, and runs 6 tests: GPS serial, sat count, GPS PPS (waits for 3 pulses), service status, atomic PPS (30s, skippable), and atomic lock (5min, skippable). Results show on both terminal and OLED as a scrolling 3-line console. Trap restarts services on exit.

`chrony.conf` has three refclocks. GPS NMEA via SHM is noselect (only there so the PPS sources can figure out what second it is). GPS PPS on /dev/pps0 has no special flags and acts as backup. Rb PPS on /dev/pps1 has prefer and trust. Only the Rb gets trust. Learned the hard way that two trusted PPS sources that disagree by nanoseconds causes chrony's falseticker algorithm to reject everything. Pool servers are there as a last resort.

`rb-calibrate.py` runs at boot. The frequency divider starts counting from whenever it powers on, so the Rb 1Hz pulse lands at a random offset within the second each time. This script waits for lock to hold 60 straight seconds, checks both PPS sources are alive, takes 10 offset samples comparing GPS PPS to Rb PPS, writes the measured offset into chrony.conf, and restarts chrony. All timeouts use time.monotonic() because chrony likes to step the clock by months at boot and that was breaking time.time() based timeouts.

`gpsd` is /etc/default/gpsd. Points at /dev/serial0 with -n so it starts polling right away without waiting for a client mostly a stock config.

`config.txt` is for defining my PPS overlays on GPIO18 and GPIO27, UART on, Bluetooth and WiFi off, I2C at 1MHz, RTC and fan overlays. Audio commented out because it wants GPIO18 which is the GPS PPS pin and I dont have any plans to make my atomic clock make sound. Geiger counter hiss on the hour would be kinda neat though. 

`antenna.py` shows satellite info and signal strength in the console. Was using it to help with positioning the GPS antenna, just a tool like diag.sh

`ntp-bench.sh` runs on a different machine and benchmarks NTP accuracy over time. Samples every 10 seconds, tracks min/max/average and threshold violations. Ctrl+C stops it and writes a report to a log file.

### Systemd services

All run as user bgoss with KillMode=control-group.

`timeserver-display.service` runs display.py. Restarts on failure.

`timeserver-leds.service` runs leds.py. Has KillSignal=SIGKILL and TimeoutStopSec=5 because the gpioset child processes don't die cleanly on SIGTERM.

`rb-calibrate.service` is a oneshot that runs rb-calibrate.py after chrony and gpsd are up. Waits about 20 min for the Rb time to warm up from cold. ConditionPathExists=/dev/pps1 means it won't run at all if the Rb PPS device isn't there.

### Kernel tuning

`nohz=off` and `isolcpus=3` are appended to /boot/firmware/cmdline.txt. nohz=off disables dynamic tick, which can cause variable latency in interrupt handling. isolcpus=3 reserves CPU core 3 so the scheduler won't put random userspace tasks on it, keeping it available for PPS interrupt processing.

`/etc/sysctl.d/99-realtime.conf` contains `kernel.sched_rt_runtime_us = -1`, which removes the default 95% cap on real-time scheduling, allowing RT-priority tasks to use the full CPU if needed. 

Ill be real I kinda blindy followed some other Time Nut's guide on this ill try and find the exact post to include here as there was WAYY more tweaks to make but im already splitting hairs using the CM4 over something like an FPGA

## NTP Tests/Benchmarking

GPS only:
```
ntpdate -q 10.0.0.208
server 10.0.0.208, stratum 1, offset +0.000393, delay 0.000130
server 10.0.0.208, stratum 1, offset +0.000443, delay 0.000075
```
I didnt do many tests during this part but the few i got showed about 400us from UTC.

Chrony internals with Rb as primary:
```
chronyc tracking
Reference ID    : 52420000 (RB)
Stratum         : 1
System time     : 0.000000098 seconds slow of NTP time
RMS offset      : 0.000000234 seconds
Frequency       : 12.669 ppm fast
Skew            : 0.015 ppm
```

Rubidium 7 Hour Benchmark: 2,614 samples @ 10s interval over LAN
```
Avg offset:    392.9us
Min offset:    0.0us
Max offset:    1506.0us

Over 50us:     2141 (81.9%)
Over 100us:    1950 (74.5%)
Over 150us:    1743 (66.6%)
Over 200us:    1571 (60.0%)
Over 250us:    1411 (53.9%)
Over 500us:    897 (34.3%)
```

So really not any better than GPS but this kinda checks out when you consider network delays and the CM4 being bottle necks. In a perfect world the server is closer to sub-microsecond from UTC but this is not a perfect world. For comparison pool.ntp.org usually gets you somewhere in the 5-50ms (+/-0.025 seconds) range so im quite happy with 400us (+/-0.0004 seconds) from UTC...just a lil better.

## Why not use PTP??

Hardware timestamping on the CM4's bcmgenet Ethernet driver is busted on the kernel im running (6.12) TX timestamps never arrive and ptp4l faults the moment it tries to send a sync packet. There are ways to work around this mostly by switching kernels or recompiling one yourself but I dont really use PTP for anything yet.

PTP is disabled for now on my setup but if the day comes i need it ill cross that bridge then.
