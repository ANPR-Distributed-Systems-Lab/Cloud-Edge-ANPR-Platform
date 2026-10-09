"""Camera pipeline: live preview, 1:1 focus view, snapshots, software auto exposure and recording.

One camera configuration serves everything:
  main  - full recording resolution, YUV420. Frames are JPEG-encoded straight from it (snapshots, recording).
  lores - small YUV420 stream. Feeds the browser preview and the auto exposure brightness measurement.
Callbacks run on picamera2's camera thread and must stay quick, so anything slow (JPEG encoding of full
frames) is handed to worker threads by holding on to the request.
"""
import collections
import csv
import io
import json
import math
import os
import queue
import threading
import time
from datetime import datetime, timezone

import numpy as np
import simplejpeg
from libcamera import ColorSpace, Transform
from libcamera import controls as lc
from picamera2 import MappedArray, Picamera2

import autoexposure
import settings as cfg
import system_info
from jsonlog import log
from storage import Storage

PREVIEW_WIDTH = 960
PREVIEW_QUALITY = 75
PREVIEW_MAX_FPS = 12.0
PREVIEW_MIN_SENSOR_FPS = 10.0  # the sensor never runs slower than this, so preview and auto exposure stay responsive
FOCUS_CROP = (960, 720)  # 1:1 pixels shown in the focus view
FOCUS_MAX_FPS = 4.0
QUEUE_DEPTH = 3  # frames waiting for a JPEG worker. Each one pins a full buffer set, so keep it small
WORKERS = 2
SNAPSHOTS_KEEP_ON_SD = 20

AWB_MODES = {
    "auto": lc.AwbModeEnum.Auto,
    "daylight": lc.AwbModeEnum.Daylight,
    "cloudy": lc.AwbModeEnum.Cloudy,
    "tungsten": lc.AwbModeEnum.Tungsten,
    "fluorescent": lc.AwbModeEnum.Fluorescent,
    "indoor": lc.AwbModeEnum.Indoor,
}


def _meminfo_bytes(key: str) -> int | None:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith(key + ":"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    return None


def _buffer_budget_bytes() -> int:
    """How much memory camera buffers may use.

    picamera2 allocates from /dev/dma_heap/vidbuf_cached (a link to the system heap, i.e. plain RAM) when the
    container sees the host's /dev. Without that link it falls back to the small CMA pool (64MB by default).
    """
    if os.path.exists("/dev/dma_heap/vidbuf_cached"):
        return int(min(1.5e9, (_meminfo_bytes("MemAvailable") or 1e9) * 0.5))
    return int((_meminfo_bytes("CmaTotal") or 64 * 1024 * 1024) * 0.6)


class FrameHub:
    """Latest JPEG, with a condition so any number of HTTP clients can wait for the next one."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self.frame: bytes | None = None
        self.seq = 0

    def publish(self, data: bytes) -> None:
        with self._cond:
            self.frame = data
            self.seq += 1
            self._cond.notify_all()

    def wait_newer(self, last_seq: int, timeout: float = 2.0) -> tuple[bytes | None, int]:
        with self._cond:
            self._cond.wait_for(lambda: self.seq != last_seq, timeout)
            return self.frame, self.seq


class Recording:
    def __init__(self, directory: str, k: int, quality: int) -> None:
        self.directory = directory
        self.k = k  # every k-th sensor frame is saved
        self.quality = quality
        self.started = time.monotonic()
        self.started_wall = datetime.now(timezone.utc)
        self.active = True
        self.tick = 0  # sensor frames seen since the start
        self.slot = 0  # capture slots handed out. A gap in the file numbers means a dropped frame
        self.saved = 0
        self.dropped = 0
        self.bytes = 0
        self.error: str | None = None
        self.stop_reason: str | None = None
        self.enc_ms = 0.0
        self.window: collections.deque = collections.deque()  # (time, bytes) for the write-speed readout
        self.csv_file = None
        self.csv = None
        self.csv_lock = threading.Lock()
        self.workers: list[threading.Thread] = []
        self.queue: queue.Queue = queue.Queue(maxsize=QUEUE_DEPTH)


class CameraService:
    def __init__(self, store: cfg.SettingsStore, storage: Storage) -> None:
        self.store = store
        self.storage = storage
        self.picam2: Picamera2 | None = None
        self.error: str | None = None
        self._running = False
        self._closing = threading.Event()
        self._cfg_lock = threading.RLock()
        self._rec_lock = threading.RLock()

        self._res_name: str | None = None
        self._main_size = (0, 0)
        self._lores_size = (0, 0)
        self._sensor_fps = 10.0
        self._k = 1

        self._meta: dict = {}
        self._meas: tuple | None = None  # (frame_no, brightness, exposure_us, gain)
        self._frame_no = 0
        self._frame_times: collections.deque = collections.deque(maxlen=30)

        self.preview = FrameHub()
        self.preview_clients = 0
        self._last_preview = 0.0
        self.focus = FrameHub()
        self.focus_info = {"sharpness": 0.0}
        self._focus_until = 0.0
        self._last_focus = 0.0
        self._snap: dict | None = None
        self.last_snapshot: dict | None = None  # {"jpeg": bytes, "info": dict}

        self._rec: Recording | None = None
        self._autostart_tried = False
        self._last_error_log = 0.0

    # --- lifecycle -------------------------------------------------------------------------------------------

    def start(self) -> None:
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()
        threading.Thread(target=self._ae_loop, name="auto-exposure", daemon=True).start()
        self._open()

    def close(self) -> None:
        self._closing.set()
        self.stop_recording("shutdown")
        with self._cfg_lock:
            if self.picam2 is not None:
                try:
                    self.picam2.stop()
                    self.picam2.close()
                except Exception as e:  # shutting down anyway
                    log("camera_close_error", error=str(e))
                self.picam2 = None
                self._running = False

    def _open(self) -> None:
        with self._cfg_lock:
            try:
                if self.picam2 is None:
                    self.picam2 = Picamera2()
                    self.picam2.post_callback = self._on_frame
                self._configure()
                self.error = None
            except Exception as e:
                self._running = False
                self.error = self._explain(e)
                log("camera_open_failed", error=str(e))
                if self.picam2 is not None:
                    try:
                        self.picam2.close()
                    except Exception:
                        pass
                    self.picam2 = None

    @staticmethod
    def _explain(e: Exception) -> str:
        if isinstance(e, OSError) and e.errno == 12:
            return ("Out of memory for camera buffers. The container must see the host's /dev (volume /dev:/dev), "
                    "otherwise buffers come from the small CMA pool. Or pick a lower resolution")
        return str(e)

    # --- configuration ---------------------------------------------------------------------------------------

    def _rates(self, rec: dict) -> tuple[float, int]:
        """Sensor fps and decimation k so that every k-th sensor frame is a recorded frame at exactly rec['fps']."""
        fps = rec["fps"]
        limit = cfg.MAX_SENSOR_FPS[rec["resolution"]]
        k = max(1, math.ceil(PREVIEW_MIN_SENSOR_FPS / fps))
        while k > 1 and fps * k > limit:
            k -= 1
        return fps * k, k

    def _controls(self, s: dict) -> dict:
        ex, wb, rec = s["exposure"], s["white_balance"], s["recording"]
        sensor_fps, _ = self._rates(rec)
        duration = int(1_000_000 / sensor_fps)
        ctrl: dict = {"AeEnable": False, "FrameDurationLimits": (duration, duration)}
        if ex["mode"] == "manual":
            ctrl["ExposureTime"] = int(ex["exposure_us"])
            ctrl["AnalogueGain"] = float(ex["gain"])
        elif ex["mode"] == "auto_gain":
            ctrl["ExposureTime"] = int(ex["exposure_us"])
        elif ex["mode"] == "auto_exposure":
            ctrl["AnalogueGain"] = float(ex["gain"])
        if wb["mode"] == "manual":
            ctrl["AwbEnable"] = False
            ctrl["ColourGains"] = (float(wb["red_gain"]), float(wb["blue_gain"]))
        else:
            ctrl["AwbEnable"] = True
            ctrl["AwbMode"] = AWB_MODES[wb["mode"]]
        return ctrl

    def _configure(self) -> None:
        """(Re)build the camera configuration from the stored settings and start the sensor."""
        with self._cfg_lock:
            s = self.store.get()
            rec = s["recording"]
            width, height = cfg.RESOLUTIONS[rec["resolution"]]
            lores_w = min(PREVIEW_WIDTH, width)
            lores_h = int(round(lores_w * height / width / 2)) * 2
            self._sensor_fps, self._k = self._rates(rec)

            # A buffer set is main + lores + the raw sensor stream. Several are held by the JPEG workers at once.
            per_set = width * height * 3.2
            count = int(min(8, max(3, _buffer_budget_bytes() // per_set)))

            if self._running:
                self.picam2.stop()
                self._running = False
            config = self.picam2.create_video_configuration(
                main={"size": (width, height), "format": "YUV420"},
                lores={"size": (lores_w, lores_h), "format": "YUV420"},
                controls=self._controls(s),
                transform=Transform(hflip=s["camera"]["hflip"], vflip=s["camera"]["vflip"]),
                buffer_count=count,
                queue=False,
            )
            config["colour_space"] = ColorSpace.Sycc()  # full-range YCbCr, what JPEG (JFIF) expects
            self.picam2.configure(config)
            self.picam2.options["quality"] = rec["jpeg_quality"]
            self.picam2.start()
            self._running = True
            self._res_name = rec["resolution"]
            self._main_size = (width, height)
            self._lores_size = (lores_w, lores_h)
            self._meas = None
            log("camera_started", resolution=self._res_name, lores=[lores_w, lores_h], sensor_fps=self._sensor_fps,
                decimation=self._k, buffers=count)

    def update_settings(self, patch: dict) -> dict:
        """Apply a partial settings update. Returns the new settings; raises ValueError if it cannot be applied now."""
        with self._cfg_lock:
            old = self.store.get()
            if self._rec is not None:
                for key in ("fps", "resolution", "jpeg_quality"):
                    if key in patch.get("recording", {}) and patch["recording"][key] != old["recording"][key]:
                        raise ValueError("Stop recording before changing fps, resolution or JPEG quality")
                for key in ("hflip", "vflip"):
                    if key in patch.get("camera", {}) and bool(patch["camera"][key]) != old["camera"][key]:
                        raise ValueError("Stop recording before flipping the image")
            new = self.store.update(patch)
            if self.picam2 is None:
                return new
            try:
                if new["recording"]["resolution"] != self._res_name or new["camera"] != old["camera"]:
                    self._configure()
                else:
                    self.picam2.set_controls(self._controls(new))
                    self._sensor_fps, self._k = self._rates(new["recording"])
                    self.picam2.options["quality"] = new["recording"]["jpeg_quality"]
                self.error = None
            except Exception as e:
                self.error = self._explain(e)
                log("apply_settings_failed", error=str(e))
                raise ValueError(self.error)
            return new

    def lock_white_balance(self) -> dict:
        """Freeze the current automatic white balance as manual gains (consistent colours across a data set)."""
        gains = self._meta.get("ColourGains")
        if not gains:
            raise ValueError("No colour gains available yet")
        return self.update_settings({"white_balance": {"mode": "manual", "red_gain": round(gains[0], 3), "blue_gain": round(gains[1], 3)}})

    def _limits(self) -> tuple:
        """(min exposure us, hardware max exposure us, min gain, hardware max gain) at the current frame rate."""
        t_max = 1_000_000 / self._sensor_fps * 0.97
        g_max = 16.0
        try:
            g_max = float(self.picam2.camera_controls["AnalogueGain"][1])
        except Exception:
            pass
        return 30.0, t_max, 1.0, g_max

    # --- per frame -------------------------------------------------------------------------------------------

    def _on_frame(self, request) -> None:
        try:
            now = time.monotonic()
            md = request.get_metadata()
            self._frame_no += 1
            self._frame_times.append(now)
            self._meta = md

            with MappedArray(request, "lores") as m:
                arr = m.array
                lw, lh = self._lores_size
                y = arr[:lh, :lw]
                roi = y[lh // 5 : lh * 4 // 5 : 4, lw // 5 : lw * 4 // 5 : 4]
                gain = md.get("AnalogueGain", 1.0) * md.get("DigitalGain", 1.0)  # brightness depends on both
                self._meas = (self._frame_no, float(roi.mean()) / 255.0, md.get("ExposureTime", 0), gain)
                if self.preview_clients > 0 and now - self._last_preview >= 1 / PREVIEW_MAX_FPS:
                    self._last_preview = now
                    self.preview.publish(self._encode_yuv420(arr, lw, lh, PREVIEW_QUALITY))

            if now < self._focus_until and now - self._last_focus >= 1 / FOCUS_MAX_FPS:
                self._last_focus = now
                self._focus_frame(request)

            snap = self._snap
            if snap is not None and snap["request"] is None:
                request.acquire()
                snap["request"] = request
                snap["event"].set()

            rec = self._rec
            if rec is not None and rec.active:
                rec.tick += 1
                if (rec.tick - 1) % rec.k == 0:
                    slot = rec.slot
                    rec.slot += 1
                    request.acquire()
                    try:
                        rec.queue.put_nowait((request, slot, datetime.now(timezone.utc)))
                    except queue.Full:
                        request.release()
                        rec.dropped += 1
        except Exception as e:  # never let an error kill the camera thread
            if time.monotonic() - self._last_error_log > 5:
                self._last_error_log = time.monotonic()
                log("frame_callback_error", error=repr(e))

    @staticmethod
    def _encode_yuv420(arr: np.ndarray, width: int, height: int, quality: int) -> bytes:
        """JPEG from a YUV420 buffer without copying it (same plane layout handling as picamera2's own save)."""
        reshaped = arr.reshape((arr.shape[0] * 2, arr.strides[0] // 2))
        y = arr[:height, :width]
        u = reshaped[2 * height : 2 * height + height // 2, : width // 2]
        v = reshaped[2 * height + height // 2 :, : width // 2]
        return simplejpeg.encode_jpeg_yuv_planes(y, u, v, quality)

    def _focus_crop(self, y: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
        width, height = self._main_size
        crop_w, crop_h = min(FOCUS_CROP[0], width), min(FOCUS_CROP[1], height)
        roi = self.store.get()["focus_roi"]
        x0 = int(min(max(roi["x"] * width - crop_w / 2, 0), width - crop_w))
        y0 = int(min(max(roi["y"] * height - crop_h / 2, 0), height - crop_h))
        return y[y0 : y0 + crop_h, x0 : x0 + crop_w], (x0, y0)

    @staticmethod
    def _sharpness(crop: np.ndarray) -> float:
        """Variance of the Laplacian: higher is sharper. Only meaningful relative to other readings of the same scene."""
        c = crop.astype(np.int16)
        lap = 4 * c[1:-1, 1:-1] - c[:-2, 1:-1] - c[2:, 1:-1] - c[1:-1, :-2] - c[1:-1, 2:]
        return float(lap.astype(np.float32).var())

    def _focus_frame(self, request) -> None:
        width, height = self._main_size
        with MappedArray(request, "main") as m:
            crop, origin = self._focus_crop(m.array[:height, :width])
            self.focus_info = {"sharpness": self._sharpness(crop), "origin": origin, "size": [crop.shape[1], crop.shape[0]]}
            self.focus.publish(simplejpeg.encode_jpeg(np.ascontiguousarray(crop[:, :, None]), quality=85, colorspace="GRAY"))

    def focus_requested(self) -> None:
        """Called by the HTTP side while someone is looking at the focus view."""
        self._focus_until = time.monotonic() + 3.0

    # --- auto exposure ---------------------------------------------------------------------------------------

    def _ae_loop(self) -> None:
        last_frame = -1
        while not self._closing.wait(0.1):
            try:
                ex = self.store.get()["exposure"]
                meas = self._meas
                if ex["mode"] == "manual" or not self._running or meas is None or meas[0] == last_frame:
                    continue
                last_frame = meas[0]
                _, brightness, t, g = meas
                t_new, g_new = autoexposure.next_exposure(ex["mode"], brightness, t, g, ex, self._limits())
                if abs(t_new - t) > 0.5 or abs(g_new - g) > 0.002:
                    self.picam2.set_controls({"ExposureTime": int(t_new), "AnalogueGain": float(g_new)})
            except Exception as e:
                log("auto_exposure_error", error=repr(e))

    # --- snapshots -------------------------------------------------------------------------------------------

    def snapshot(self) -> dict:
        """Full resolution JPEG of the next frame. Saved next to the recordings (or on the SD card if no USB)."""
        if not self._running:
            raise RuntimeError("Camera is not running")
        snap = {"event": threading.Event(), "request": None}
        self._snap = snap
        try:
            if not snap["event"].wait(10):
                raise RuntimeError("Timed out waiting for a frame")
        finally:
            self._snap = None
        request = snap["request"]
        try:
            md = request.get_metadata()
            buf = io.BytesIO()
            started = time.monotonic()
            request.save("main", buf, format="jpeg")
            jpeg = buf.getvalue()
            encode_ms = (time.monotonic() - started) * 1000
            width, height = self._main_size
            with MappedArray(request, "main") as m:
                crop, _ = self._focus_crop(m.array[:height, :width])
                sharpness = self._sharpness(crop)
        finally:
            request.release()

        name = datetime.now().strftime("snap_%Y%m%d_%H%M%S.jpg")
        directory = os.path.join(self.storage.root, "snapshots") if self.storage.ready() else os.path.join(cfg.CONFIG_DIR, "snapshots")
        path = None
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, name)
            with open(path, "wb") as f:
                f.write(jpeg)
            if directory.startswith(cfg.CONFIG_DIR):
                files = sorted(os.listdir(directory))
                for old in files[:-SNAPSHOTS_KEEP_ON_SD]:
                    os.remove(os.path.join(directory, old))
        except OSError as e:
            log("snapshot_save_failed", error=str(e))
            path = None
        info = {
            "name": name,
            "path": path,
            "width": self._main_size[0],
            "height": self._main_size[1],
            "bytes": len(jpeg),
            "encode_ms": round(encode_ms),
            "sharpness": round(sharpness, 1),
            "exposure_us": md.get("ExposureTime"),
            "gain": round(md.get("AnalogueGain", 0) * md.get("DigitalGain", 1.0), 2),
            "colour_gains": [round(x, 3) for x in md.get("ColourGains", (0, 0))],
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self.last_snapshot = {"jpeg": jpeg, "info": info}
        log("snapshot", **info)
        return info

    # --- recording -------------------------------------------------------------------------------------------

    def start_recording(self, reason: str = "user") -> None:
        with self._rec_lock:
            if self._rec is not None:
                raise RuntimeError("Already recording")
            if not self._running:
                raise RuntimeError("Camera is not running")
            if not self.storage.ready() and not self.storage.mount():
                raise RuntimeError(self.storage.error or "USB stick is not available")
            s = self.store.get()
            usage = self.storage.usage()
            if usage is not None and usage["free"] < s["recording"]["min_free_mb"] * 1_000_000:
                raise RuntimeError("Not enough free space on the USB stick")

            base = datetime.now().strftime("session_%Y%m%d_%H%M%S")
            directory = os.path.join(self.storage.root, base)
            suffix = 1
            while os.path.exists(directory):
                suffix += 1
                directory = os.path.join(self.storage.root, f"{base}_{suffix}")
            os.makedirs(directory)

            rec = Recording(directory, self._k, s["recording"]["jpeg_quality"])
            with open(os.path.join(directory, "session.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "started_utc": rec.started_wall.isoformat(timespec="seconds"),
                    "settings": s,
                    "sensor_fps": self._sensor_fps,
                    "decimation": self._k,
                    "main_size": list(self._main_size),
                    "start_reason": reason,
                }, f, indent=2)
            rec.csv_file = open(os.path.join(directory, "frames.csv"), "w", newline="", encoding="utf-8")
            rec.csv = csv.writer(rec.csv_file)
            rec.csv.writerow(["file", "time_utc", "sensor_timestamp_ns", "exposure_us", "analogue_gain", "digital_gain",
                              "red_gain", "blue_gain", "lux", "bytes"])
            self.picam2.options["quality"] = rec.quality
            for i in range(WORKERS):
                worker = threading.Thread(target=self._worker, args=(rec,), name=f"jpeg-worker-{i}", daemon=True)
                worker.start()
                rec.workers.append(worker)
            self._rec = rec
            log("recording_started", directory=directory, fps=s["recording"]["fps"], reason=reason)

    def stop_recording(self, reason: str = "user") -> None:
        with self._rec_lock:
            rec = self._rec
            if rec is None:
                return
            rec.active = False
            rec.stop_reason = reason
            for _ in rec.workers:
                rec.queue.put(None)  # sentinels queue up behind any frames still waiting
            for worker in rec.workers:
                worker.join(timeout=60)
            try:
                rec.csv_file.flush()
                rec.csv_file.close()
                with open(os.path.join(rec.directory, "summary.json"), "w", encoding="utf-8") as f:
                    json.dump({
                        "stopped_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "reason": reason,
                        "saved": rec.saved,
                        "dropped": rec.dropped,
                        "seconds": round(time.monotonic() - rec.started, 1),
                        "bytes": rec.bytes,
                        "error": rec.error,
                    }, f, indent=2)
            except OSError as e:
                log("recording_summary_failed", error=str(e))
            os.sync()
            self._rec = None
            log("recording_stopped", reason=reason, saved=rec.saved, dropped=rec.dropped, bytes=rec.bytes, error=rec.error)

    def _worker(self, rec: Recording) -> None:
        while True:
            item = rec.queue.get()
            if item is None:
                return
            request, slot, wall = item
            try:
                self._save_frame(rec, request, slot, wall)
            except Exception as e:
                rec.error = rec.error or repr(e)
                log("frame_save_failed", slot=slot, error=repr(e))
            finally:
                request.release()

    def _save_frame(self, rec: Recording, request, slot: int, wall: datetime) -> None:
        md = request.get_metadata()
        folder = os.path.join(rec.directory, f"{slot // 1000:04d}")
        os.makedirs(folder, exist_ok=True)
        name = f"img_{slot:06d}.jpg"
        final = os.path.join(folder, name)
        part = os.path.join(folder, f".{name[:-4]}.part.jpg")  # picamera2 picks the format from the extension
        started = time.monotonic()
        request.save("main", part)
        os.replace(part, final)  # a half-written file never carries the final name
        size = os.path.getsize(final)
        now = time.monotonic()
        gains = md.get("ColourGains", (0.0, 0.0))
        with rec.csv_lock:
            rec.csv.writerow([
                f"{slot // 1000:04d}/{name}", wall.isoformat(timespec="milliseconds"), md.get("SensorTimestamp", ""),
                md.get("ExposureTime", ""), round(md.get("AnalogueGain", 0), 3), round(md.get("DigitalGain", 1.0), 3),
                round(gains[0], 3), round(gains[1], 3), round(md.get("Lux", 0), 1), size,
            ])
            rec.saved += 1
            rec.bytes += size
            rec.enc_ms = 0.8 * rec.enc_ms + 0.2 * (now - started) * 1000 if rec.saved > 1 else (now - started) * 1000
            rec.window.append((now, size))
            while rec.window and now - rec.window[0][0] > 5:
                rec.window.popleft()
            if rec.saved % 10 == 0:
                rec.csv_file.flush()

    # --- background upkeep -----------------------------------------------------------------------------------

    def _housekeeping(self) -> None:
        ticks = 0
        while not self._closing.wait(1.0):
            ticks += 1
            try:
                if self._rec is None or ticks % 5 == 0:
                    self.storage.poll()
                if not self._running and not self._closing.is_set() and ticks % 5 == 0:
                    self._open()
                rec = self._rec
                if rec is not None:
                    usage = self.storage.usage()
                    limit = self.store.get()["recording"]["min_free_mb"] * 1_000_000
                    if rec.error:
                        self.stop_recording("storage_error")
                    elif not self.storage.ready():
                        self.stop_recording("usb_removed")
                    elif usage is not None and usage["free"] < limit:
                        self.stop_recording("disk_full")
                    elif ticks % 10 == 0:
                        os.sync()
                elif (not self._autostart_tried and self._running and self.store.get()["recording"]["autostart"]
                      and self.storage.ready()):
                    self._autostart_tried = True
                    self.start_recording("autostart")
            except Exception as e:
                log("housekeeping_error", error=repr(e))

    # --- status ----------------------------------------------------------------------------------------------

    def measured_fps(self) -> float:
        times = list(self._frame_times)
        if len(times) < 2 or time.monotonic() - times[-1] > 2:
            return 0.0
        return (len(times) - 1) / (times[-1] - times[0])

    def recording_status(self) -> dict | None:
        rec = self._rec
        if rec is None:
            return None
        now = time.monotonic()
        window = list(rec.window)
        speed = sum(b for _, b in window) / max(now - window[0][0], 1.0) if window else 0.0
        return {
            "saved": rec.saved,
            "dropped": rec.dropped,
            "queued": rec.queue.qsize(),
            "bytes": rec.bytes,
            "seconds": round(now - rec.started),
            "directory": os.path.basename(rec.directory),
            "write_bytes_per_s": speed,
            "encode_ms": round(rec.enc_ms),
            "error": rec.error,
        }

    def status(self) -> dict:
        meta = self._meta
        gains = meta.get("ColourGains") or (0.0, 0.0)
        limits = self._limits() if self.picam2 is not None else (30, 33000, 1.0, 16.0)
        return {
            "camera": {
                "running": self._running,
                "error": self.error,
                "resolution": self._res_name,
                "sensor_fps": round(self._sensor_fps, 2),
                "measured_fps": round(self.measured_fps(), 1),
                "decimation": self._k,
                "limits": {"exposure_us": [limits[0], limits[1]], "gain": [limits[2], limits[3]]},
                "actual": {
                    "exposure_us": meta.get("ExposureTime"),
                    "gain": round(meta.get("AnalogueGain", 0) * meta.get("DigitalGain", 1.0), 3),
                    "red_gain": round(gains[0], 3),
                    "blue_gain": round(gains[1], 3),
                    "lux": round(meta.get("Lux", 0), 1),
                    "brightness": round(self._meas[1], 3) if self._meas else None,
                },
            },
            "recording": self.recording_status(),
            "storage": self.storage.status(),
            "system": {"temp_c": system_info.cpu_temp_c(), "power": system_info.power_flags()},
            "snapshot": self.last_snapshot["info"] if self.last_snapshot else None,
            "focus": self.focus_info,
        }
