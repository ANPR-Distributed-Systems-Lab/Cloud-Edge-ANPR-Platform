"""Pi health values worth watching in a hot car on a power bank: CPU temperature and throttling flags."""
import fcntl
import os
import struct


def cpu_temp_c() -> float | None:
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return int(f.read()) / 1000
    except (OSError, ValueError):
        return None


def _vcgencmd(command: str) -> str:
    """Firmware command through the /dev/vcio mailbox, what the vcgencmd binary does (the image has no binary)."""
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
