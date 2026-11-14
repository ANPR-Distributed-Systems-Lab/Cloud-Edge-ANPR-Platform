"""Pi health values worth watching in a hot car on a power bank: CPU temperature and load, memory, disk, uptime,
throttling flags, the IP."""
import os
import shutil
import socket
import struct
import time
from pathlib import Path

import psutil

MEGABYTE = 1_000_000


def cpu_temp_c() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except (OSError, ValueError):
        return None


def cpu_usage_percent() -> float:
    """Load of all cores since the previous call (the first call after the start reports 0)."""
    return psutil.cpu_percent(interval=None)


def ram_usage_percent() -> float:
    return psutil.virtual_memory().percent


def disk_free_mb(path: Path) -> int:
    return shutil.disk_usage(path).free // MEGABYTE


def uptime_seconds() -> int:
    return int(time.time() - psutil.boot_time())


def _vcgencmd(command: str) -> str:
    """Firmware command through the /dev/vcio mailbox, what the vcgencmd binary does (the image has no binary)."""
    import fcntl  # Linux only; imported here so the module also loads on a development PC

    buf = bytearray(263 * 4)
    struct.pack_into("<5I", buf, 0, len(buf), 0, 0x00030080, 1024, 0)
    struct.pack_into(f"{len(command) + 1}s", buf, 24, command.encode())
    request = 0xC0000000 | (struct.calcsize("P") << 16) | (100 << 8)
    fd = os.open("/dev/vcio", os.O_RDWR)
    try:
        fcntl.ioctl(fd, request, buf, True)
    finally:
        os.close(fd)
    if struct.unpack_from("<I", buf, 20)[0]:
        raise OSError(f"vcgencmd {command!r} failed")
    return bytes(buf[24:]).split(b"\0", 1)[0].decode()


def power_flags() -> dict | None:
    """Decode `vcgencmd get_throttled`. None when the firmware cannot be queried."""
    try:
        flags = int(_vcgencmd("get_throttled").split("=")[1], 16)
    except (OSError, ValueError, IndexError):
        return None
    return {
        "undervoltage_now": bool(flags & 0x1),
        "throttled_now": bool(flags & 0x4),
        "temp_limit_now": bool(flags & 0x8),
        "undervoltage_occurred": bool(flags & 0x10000),
        "throttled_occurred": bool(flags & 0x40000),
    }


def local_ip() -> str:
    """IP of the interface that would be used to reach the network (no packet is sent)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("192.0.2.1", 9))
        return sock.getsockname()[0]
    except OSError:
        return "no network"
    finally:
        sock.close()
