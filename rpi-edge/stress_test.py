"""Power-supply stress experiment for the Raspberry Pi 5.

The tact switch (GPIO22) toggles a CPU stress test on/off. The 4x20 LCD shows
CPU load, RAM usage, CPU temperature and the 5V input voltage.
"""
import fcntl
import hashlib
import json
import os
import re
import struct
import threading
import time
from datetime import datetime, timezone

import psutil
from gpiozero import Button, Buzzer, CPUTemperature, LED
from RPLCD.i2c import CharLCD

REFRESH_S = 1.0

# Lines of `vcgencmd pmic_read_adc`, e.g. "EXT5V_V volt(24)=5.04912V"
_PMIC_LINE = re.compile(r"^\s*(\S+)_([AV]) (?:current|volt)\(\d+\)=([\d.]+)[AV]$")


def log(event: str, **fields) -> None:
    print(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "event": event, **fields}), flush=True)


def vcgencmd(command: str) -> str:
    """Run a firmware command through the /dev/vcio mailbox, the same way the vcgencmd binary does.

    Done in pure Python because the slim container image has no vcgencmd binary.
    """
    buf = bytearray(263 * 4)
    struct.pack_into("<5I", buf, 0, len(buf), 0, 0x00030080, 1024, 0)  # size, request, GET_GENCMD_RESULT tag, buffer size, request size
    struct.pack_into(f"{len(command) + 1}s", buf, 24, command.encode())
    ioctl_mbox_property = 0xC0000000 | (struct.calcsize("P") << 16) | (100 << 8)
    fd = os.open("/dev/vcio", os.O_RDWR)
    try:
        fcntl.ioctl(fd, ioctl_mbox_property, buf, True)
    finally:
        os.close(fd)
    if error := struct.unpack_from("<I", buf, 20)[0]:
        raise OSError(f"vcgencmd {command!r} failed with firmware error {error}")
    return bytes(buf[24:]).split(b"\0", 1)[0].decode()


def read_input_voltage() -> float:
    """5V input voltage [V] measured by the PMIC. Pi 5 has no input current sensor, so no current is reported."""
    for line in vcgencmd("pmic_read_adc").splitlines():
        if m := _PMIC_LINE.match(line):
            if m[1] == "EXT5V" and m[2] == "V":
                return float(m[3])
    raise OSError("EXT5V_V not found in pmic_read_adc output")


def power_status() -> str:
    flags = int(vcgencmd("get_throttled").split("=")[1], 16)
    if flags & 0x1:
        return "UNDERVOLTAGE NOW!"
    if flags & 0x4:
        return "THROTTLED"
    if flags & 0x10000:
        return "UV occurred"
    return "Power OK"


class Stress:
    """Loads every core with plain threads, pbkdf2_hmac releases the GIL.

    It is a register-only loop with no memory stalls, so it draws close to peak core current
    (measured ~5A on VDD_CORE). Hashing a big buffer is memory-bound and barely beats idle.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    @property
    def running(self) -> bool:
        return bool(self._threads)

    def start(self) -> None:
        self._stop.clear()
        self._threads = [threading.Thread(target=self._burn, daemon=True) for _ in range(os.cpu_count())]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join()
        self._threads = []

    def _burn(self) -> None:
        while not self._stop.is_set():
            hashlib.pbkdf2_hmac("sha256", b"stress", b"stress", 100_000)  # ~0.15s, bounds how long stop() waits


def main() -> None:
    lcd = CharLCD(
        i2c_expander="PCF8574",
        address=0x27,
        port=1,
        cols=20,
        rows=4,
        dotsize=8,
        charmap="A02",
        auto_linebreaks=True,
    )
    led = LED(17)
    buzzer = Buzzer(27)
    button = Button(22, bounce_time=0.05)
    cpu_temp = CPUTemperature()
    stress = Stress()

    def toggle() -> None:
        if stress.running:
            stress.stop()
            led.off()
        else:
            stress.start()
            led.on()
        buzzer.beep(0.1, 0.1, 1)
        log("stress", running=stress.running)

    button.when_pressed = toggle

    lcd.clear()
    psutil.cpu_percent()  # the first call has nothing to compare against, prime it
    log("started")

    while True:
        time.sleep(REFRESH_S)
        try:
            volts = read_input_voltage()
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            temp = cpu_temp.temperature
            status = power_status()
            lines = [
                f"CPU {cpu:3.0f}%  RAM {ram:3.0f}%",
                f"Temp {temp:4.1f}C  {'STRESS' if stress.running else 'idle'}",
                f"Input: {volts:.2f}V",
                status,
            ]
            for row, text in enumerate(lines):
                lcd.cursor_pos = (row, 0)
                lcd.write_string(text.ljust(20)[:20])
            log(
                "metrics",
                cpu_percent=cpu,
                ram_percent=ram,
                cpu_temp_c=temp,
                input_v=round(volts, 3),
                power_status=status,
                stress=stress.running,
            )
        except OSError as e:
            # I2C / mailbox glitches are likely exactly when the supply is struggling, keep the experiment running
            log("error", error=str(e))


if __name__ == "__main__":
    main()
