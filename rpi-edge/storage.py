"""The USB stick: finds it, mounts it inside the container, unmounts it safely and reports free space.

The container is privileged and sees the host's /dev, so it can mount the stick itself (no host fstab
changes). Recording is only allowed while a real USB device is mounted at DATA_DIR, so a missing stick
can never silently fill the SD card.
"""
import os
import re
import shutil
import subprocess
import threading

from jsonlog import log

DATA_DIR = os.environ.get("DATA_DIR", "/data")
USB_DEVICE = os.environ.get("USB_DEVICE")  # explicit device, e.g. /dev/sda1. Default: first USB disk found
ALLOW_UNMOUNTED = os.environ.get("DATA_ALLOW_UNMOUNTED") == "1"  # development only: write to DATA_DIR on the SD card
SUBDIR = "rpi-edge"


class Storage:
    def __init__(self) -> None:
        self.mount_point = DATA_DIR
        self._lock = threading.RLock()
        self.error: str | None = None
        self._ejected_device: str | None = None  # no automatic re-mount of a stick the user ejected, until it is unplugged

    @property
    def root(self) -> str:
        """Directory all recordings go into."""
        return os.path.join(self.mount_point, SUBDIR)

    # --- discovery -------------------------------------------------------------------------------------------

    def find_device(self) -> str | None:
        if USB_DEVICE:
            return USB_DEVICE if os.path.exists(USB_DEVICE) else None
        try:
            names = sorted(os.listdir("/sys/block"))
        except OSError:
            return None
        for name in names:
            if not re.fullmatch(r"sd[a-z]+", name):
                continue
            try:
                with open(f"/sys/block/{name}/size") as f:
                    if int(f.read()) == 0:  # a card reader shows up as a disk even with no card in it
                        continue
            except (OSError, ValueError):
                continue
            parts = sorted(p for p in os.listdir(f"/sys/block/{name}") if re.fullmatch(rf"{name}\d+", p))
            device = f"/dev/{parts[0] if parts else name}"
            if os.path.exists(device):
                return device
        return None

    def mounted_source(self) -> str | None:
        """Block device mounted at the data directory, if any."""
        try:
            with open("/proc/self/mountinfo") as f:
                for line in f:
                    left, _, right = line.partition(" - ")
                    fields = left.split()
                    if len(fields) > 4 and fields[4] == self.mount_point:
                        return right.split()[1]
        except OSError:
            pass
        return None

    def ready(self) -> bool:
        if ALLOW_UNMOUNTED:
            return os.path.isdir(self.mount_point)
        source = self.mounted_source()
        if source is None:
            return False
        return source == USB_DEVICE or re.fullmatch(r"/dev/sd[a-z]+\d*", source) is not None

    # --- mount / eject ---------------------------------------------------------------------------------------

    def _run(self, *cmd: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, str(e)
        return result.returncode == 0, (result.stderr or result.stdout).strip()

    def mount(self) -> bool:
        with self._lock:
            if self.ready():
                return True
            device = self.find_device()
            if device is None:
                self.error = "No USB stick found"
                return False
            os.makedirs(self.mount_point, exist_ok=True)
            ok, message = self._run("mount", "-o", "noatime", device, self.mount_point)
            if not ok:
                fs_ok, fs_type = self._run("blkid", "-o", "value", "-s", "TYPE", device)
                if fs_ok and fs_type == "ntfs":  # the kernel driver is called ntfs3
                    ok, message = self._run("mount", "-t", "ntfs3", "-o", "noatime", device, self.mount_point)
            if not ok:
                self.error = f"Mounting {device} failed: {message}"
                log("usb_mount_failed", device=device, error=message)
                return False
            try:
                os.makedirs(self.root, exist_ok=True)
                probe = os.path.join(self.root, ".write-test")
                with open(probe, "w") as f:
                    f.write("ok")
                os.remove(probe)
            except OSError as e:
                self._run("umount", self.mount_point)
                self.error = f"{device} is mounted read-only or damaged ({e}). Check it on Windows (chkdsk) and retry"
                log("usb_not_writable", device=device, error=str(e))
                return False
            self.error = None
            log("usb_mounted", device=device)
            return True

    def eject(self) -> bool:
        """Flush and unmount so the stick can be pulled out. Recording must be stopped by the caller."""
        with self._lock:
            device = self.mounted_source()
            if device is None:
                return True
            os.sync()
            ok, message = self._run("umount", self.mount_point)
            if not ok:
                self.error = f"Unmount failed: {message}"
                log("usb_eject_failed", error=message)
                return False
            self._ejected_device = self.find_device() or device
            self.error = None
            log("usb_ejected", device=device)
            return True

    def poll(self) -> None:
        """Called every few seconds: mounts a newly inserted stick, drops the mount of a removed one."""
        if ALLOW_UNMOUNTED:
            return
        with self._lock:
            device = self.find_device()
            if device is None:
                self._ejected_device = None
                if self.mounted_source() is not None:  # pulled out without ejecting
                    self._run("umount", "-l", self.mount_point)
                    self.error = "USB stick was removed"
                    log("usb_removed")
                return
            if self.mounted_source() is None and device != self._ejected_device:
                self.mount()

    def allow_remount(self) -> None:
        self._ejected_device = None

    # --- status ----------------------------------------------------------------------------------------------

    def usage(self) -> dict | None:
        if not self.ready():
            return None
        try:
            total, used, free = shutil.disk_usage(self.mount_point)
        except OSError:
            return None
        return {"total": total, "used": used, "free": free}

    def status(self) -> dict:
        usage = self.usage()
        return {
            "ready": self.ready(),
            "device": self.mounted_source() or self.find_device(),
            "mounted": self.mounted_source() is not None,
            "usage": usage,
            "error": self.error,
        }
