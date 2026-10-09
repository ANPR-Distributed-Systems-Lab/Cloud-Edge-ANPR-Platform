# Training data collection (rpi-edge)

Tool for gathering road frames to train the plate detection/OCR models. It runs on the Raspberry Pi in a
container and is controlled from a browser (laptop at the desk, phone in the car). Frames are saved as
full-resolution JPEGs on a USB stick that can be read directly on Windows.

## Run it

From `rpi-edge/`, with the Docker context pointing at the Pi (see `RASPBERRY_PI_SETUP.md`):

```bash
docker compose up --build
```

Open `http://<pi-ip>:8000/`. The IP is also shown on the LCD (4th line). The container has
`restart: unless-stopped`, so it comes back by itself after the Pi is powered up in the car.

Settings are saved in a Docker volume (`/config`), they survive rebuilds and reboots.

## The page

**1. Image settings.** Applied live and used by both test shots and recording.

| Mode | Behaviour |
|---|---|
| Manual | Fixed exposure time and gain |
| Auto | Brightness is balanced by exposure time first, up to the **hard exposure limit**, and only then by gain, up to the **gain limit** |
| Auto gain | Exposure time fixed, gain automatic (up to its limit) |
| Auto exposure | Gain fixed, exposure time automatic (up to its limit) |

Also: target brightness for the auto modes, white balance (presets, manual R/B gains, or "lock current" to
freeze what the camera currently measures), recording fps, recording resolution, JPEG quality, image flips,
minimum free space and autostart.

Gain 1.0 is about ISO 100 (gain 4.0 is about ISO 400). For moving cars use a short exposure (1/1000 s or less)
and let the gain make up for the light, a blurred plate is useless for training. For a consistent data set use
a fixed white balance (daylight or "lock current") instead of automatic.

**2. Test shot and focus.** "Take photo" captures a full resolution frame (saved next to the recordings, or on
the SD card when no USB stick is mounted) and shows it in the page. "Focus view 1:1" shows an un-scaled crop of
the sensor with a sharpness number: turn the lens focus ring until the number is highest (compare only readings
of the same scene and light). Click the live preview to move the crop.

**3. Recording.** Start/stop, counters, write speed, estimated time until the stick is full, mount and
safe-eject buttons. Eject (or stop recording and wait for the LED to go off) before pulling the stick out.

fps, resolution, JPEG quality and image flips cannot be changed while recording. Exposure and white balance can.

## In the car (no laptop)

- **Tact switch (GPIO22)** starts/stops recording. **LED (GPIO17)** is on while recording. **Buzzer (GPIO27)**:
  one beep on start, two on stop, one long beep on error.
- **LCD** shows state and frame counter, free space on the stick, current shutter and ISO, IP address and CPU
  temperature (`UV!` appears when the Pi reports under-voltage).
- Optional **autostart**: recording starts by itself once the USB stick is available.

## What ends up on the stick

```
rpi-edge/
  session_YYYYMMDD_HHMMSS/
    session.json     settings used, sensor fps, resolution
    frames.csv       one row per frame (file, UTC time, sensor timestamp, exposure, gains, white balance, lux, bytes)
    summary.json     frames saved/dropped, duration, why it stopped
    0000/img_000000.jpg ...   1000 frames per folder
  snapshots/         test shots
```

A gap in the `img_NNNNNN` numbers means the frame was dropped (the stick could not keep up). Files are written
under a temporary name and renamed, so a half-written frame never has a final name.

Use **exFAT** (readable on Windows without extra tools; FAT32 and NTFS also mount). The container mounts the
stick itself, nothing has to be configured on the Pi. Recording is refused unless a USB stick is mounted, so
frames can never fill the SD card. Use a Raspberry Pi OS **Lite** image: a desktop image may auto-mount the stick
on the host as well.

## Measured on this Pi (IMX477, Pi 5 8 GB)

Frames were written to a RAM disk and to an exFAT image file on the SD card, **not to a real USB stick**, and the
scene was a dim room. Real scenes give larger JPEGs (3 to 5 MB at 12 MP).

- 12 MP (4056x3040) JPEG: about 47 ms per frame per encoder thread, 2 threads. No dropped frames at 11.5 fps
  (the sensor limit for this mode is about 11.7 fps) and over 2 minutes at 5 fps (649 frames, 0 dropped).
- Process memory stays flat (no leak over 650+ frames), CPU temperature rose from 35 to 37 °C.
- Sensor limits per resolution (fps): 4056x3040 11.7, 4056x2160 16.3, 2028x1520 45, 2028x1080 62, 1332x990 101.
- At 12 MP and 10 fps real scenes need about 40 to 50 MB/s of sustained write speed. Use a USB 3 stick in a blue
  USB 3 port, and watch the "dropped" counter and the write speed in the page on the first drive.

## Things to know

- There is no authentication: use it on a private network (phone hotspot), not on an open one.
- Only horizontal and vertical flips are available in hardware. The Pi 5 camera pipeline cannot rotate by 90°,
  so mount the camera landscape (or rotate the frames when training).
- The Pi has no battery-backed clock by default. With the phone hotspot it gets the time from the network; without
  it, timestamps in `frames.csv` can be wrong (file numbers and the sensor timestamp stay valid).
- Recording people and number plates in public places is personal data processing (GDPR). Keep the raw data set private.
- `docker compose up --watch` works for development: code changes sync and restart the app, changes to
  `pyproject.toml`, `uv.lock` or the `Dockerfile` rebuild the image.

## Troubleshooting

- **"No USB stick found"**: the stick is not detected. Check `lsblk` on the Pi.
- **"mounted read-only or damaged"**: the stick has a dirty flag. Run a disk check on Windows (`chkdsk`).
- **Camera error / `Device or resource busy`**: another process holds the camera (a leftover container,
  `rpicam-*` command). `docker ps` and stop it.
- **Dropped frames**: lower fps or resolution, or use a faster stick.
- **Black or very dark image**: lens cap, closed aperture, or too short exposure for the light.
