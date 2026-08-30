# Setting up a fresh Raspberry Pi for container-based development

This document describes a universal process for preparing a brand new,
never-before-booted Raspberry Pi (tested on Pi 5) for the following
workflow:

- code is written locally on a PC (Windows) in IntelliJ IDEA,
- it runs and builds inside Docker containers **directly on the Raspberry
  Pi**,
- with no manual file copying — `docker` on the PC talks straight to the
  Docker daemon on the Pi over SSH, and `docker compose watch` syncs code
  changes live.

End result: edit a file in IntelliJ → it auto-syncs into the running
container on the Pi → the process restarts — no manual `scp`/`rsync` and no
image rebuild on every change.

## Requirements

- Raspberry Pi (5 or newer recommended) + an adequately powered supply
  (for Pi 5: the official 27W USB-C power supply — an underpowered one is a
  common source of random freezes under load).
- microSD card (or other boot media).
- Windows PC with IntelliJ IDEA (Ultimate/Professional recommended — native
  support for `uv` and remote Docker connections).
- Docker Desktop on the PC (only the `docker`/`docker compose` client is
  actually needed; Desktop's local engine is not used — the CLI is switched
  to a remote context pointing at the Pi).

## 1. Flashing the SD card

1. Install **Raspberry Pi Imager** ([raspberrypi.com/software](https://www.raspberrypi.com/software/)).
2. Choose:
   - **Choose Device** → your Pi model
   - **Choose OS** → Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**
     (no desktop environment — it only wastes RAM/CPU, since the Pi will be
     managed exclusively over SSH)
   - **Choose Storage** → the SD card
3. Before flashing, click **Edit Settings** (key step — enables a headless
   setup, no monitor/keyboard needed):
   - **General**: hostname (e.g. `<device-name>`), username/password, WiFi
     configuration (see the networking section below), timezone/keyboard
     layout.
   - **Services**: check **Enable SSH** → **Use password authentication**
     (a passwordless SSH key is added in a later step).
4. Save the settings, confirm overwriting the card, flash.

## 2. Networking — two options

The Pi needs to be on the same network as the PC (so SSH and the Docker CLI
can reach it).

**Option A — Ethernet cable to a home router.** Simplest if you have a free
router port. WiFi setup in step 1 can then be skipped.

**Option B — Windows Mobile Hotspot** (useful when the PC gets its internet
over an Ethernet cable and its WiFi adapter is otherwise idle). The PC
becomes the gateway for the Pi — no router required at all:

1. **Settings → Network & Internet → Mobile hotspot**
2. **Share my Internet connection from**: Ethernet
3. Band: **2.4 GHz** (better compatibility/range)
4. Note the SSID and password, turn the hotspot on
5. In step 1 (Raspberry Pi Imager → Edit Settings → WiFi) enter that
   hotspot's credentials

In both options the Pi joins the network automatically on first boot — no
manual configuration is needed after power-on.

## 3. First boot

1. Insert the SD card into the Pi.
2. Connect power (and an Ethernet cable, if using Option A). The first boot,
   which includes a partition resize, takes about 1–2 minutes.
3. From the PC, check whether the Pi responds:

   ```bash
   ping <hostname>.local
   ```

4. Connect over SSH:

   ```bash
   ssh <user>@<hostname>.local
   ```

   Accept the fingerprint (`yes`), enter the password set in the Imager.

> **A note on mDNS (`.local`):** resolving `.local` names on Windows can be
> flaky — it can break after installing WSL (which creates its own virtual
> network adapter) or simply stop working mid-session (e.g. in the middle of
> a Docker build). If `.local` stops responding, see **Troubleshooting**
> below — long-term, it's best not to depend on mDNS at all.

## 4. Installing Docker on the Pi

Once connected over SSH:

```bash
sudo apt update && sudo apt full-upgrade -y
```

```bash
curl -fsSL https://get.docker.com | sudo sh
```

The official script installs Docker Engine plus the Compose v2 plugin
(needed for `docker compose watch` — the older `docker-compose` from `apt`
doesn't have it).

Add your user to the `docker` group so `sudo` isn't required for every
command:

```bash
sudo usermod -aG docker <user>
```

> **Pitfall:** name the user **explicitly**, don't rely on `$USER` if you're
> in a root shell (e.g. after `sudo -i`) — `$USER` in such a shell often
> expands to `root`, so the group gets added to root instead of your
> account, and you'll keep getting `permission denied` on `docker run`.

The group change needs a fresh session — a full reboot is the safest bet:

```bash
sudo reboot
```

After reconnecting over SSH, test:

```bash
docker run hello-world
```

Should work without `sudo` and without a permission error.

## 5. Passwordless SSH key

On the PC (Windows), in PowerShell:

```bash
ssh-keygen -t ed25519 -C "<description>"
```

Press Enter through every prompt (default path, no passphrase — for
convenience in the dev loop).

Upload the public key to the Pi:

```bash
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh <user>@<hostname>.local "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"
```

Test (should log in without asking for a password):

```bash
ssh <user>@<hostname>.local
```

### Recommended: an alias in `~/.ssh/config` instead of `.local`

To avoid depending on mDNS (see the note in step 3), it's worth adding an
alias based on the Pi's actual IP address (found e.g. in the router's or
Windows Hotspot's device list):

```bash
notepad $env:USERPROFILE\.ssh\config
```

```
Host <alias>
    HostName <Pi-IP>
    User <user>
```

From now on, connect with: `ssh <alias>` — works regardless of mDNS status.

## 6. Docker CLI on the PC + Docker Context

Install **Docker Desktop** on Windows (only the `docker` client is actually
needed).

Create a context pointing at the Pi:

```bash
docker context create rpi --docker "host=ssh://<user>@<hostname>.local"
```

(or with the alias from `~/.ssh/config`: `host=ssh://<alias>`)

Switch the active context:

```bash
docker context use rpi
```

Test — should return an empty container list **with no connection error**:

```bash
docker ps
```

From this point on, every `docker build` / `docker compose up` run locally
on the PC actually executes on the Docker engine on the Raspberry Pi.

## 7. IntelliJ IDEA integration

1. **Settings → Build, Execution, Deployment → Docker** → **+** →
   **Docker context** → select the `rpi` context (the IDE auto-detects it
   since it already exists in the CLI).
2. Open the **Services** window — it should show a live connection to the
   Pi.
3. **Run → Edit Configurations → + → Docker → Docker-compose**:
   - **Server**: pick the `rpi` connection created in step 1 (important —
     with multiple Docker connections active it's easy to accidentally
     build something locally instead of on the Pi)
   - **Compose files**: point to `compose.yaml`
4. Running via the ▶ button on this configuration builds/starts containers
   on the Pi, with live logs in the **Services** window.

## 8. Python dependency management — `uv`

The project uses `uv` instead of plain `venv`/`pip` — faster builds (this
matters because the image build happens on the Pi's CPU, which is slower
than the PC) and a consistent lockfile (`uv.lock`) shared between the local
environment and the container image.

Installing `uv` on Windows:

```bash
winget install --id=astral-sh.uv -e
```

In IntelliJ: when creating a new Python project, pick **uv** as the
environment manager (if available natively in the wizard) — the IDE creates
`pyproject.toml` and `.venv` for you.

Add dependencies only through:

```bash
uv add <package>
```

(not a manual `pip install` inside the active venv — that doesn't get
recorded in `pyproject.toml`/`uv.lock`, so the lockfile stops reflecting the
actual state of the environment).

## 9. Layout for `docker compose watch`

Target file layout for a module (e.g. `rpi-edge/`):

```
pyproject.toml
uv.lock
main.py
Dockerfile
compose.yaml
.dockerignore
```

Key elements of the `Dockerfile`:

- a Python base image matching `requires-python` from `pyproject.toml`
  (multi-arch — the same tag automatically pulls the arm64 variant when
  building on the Pi),
- `ENV PYTHONUNBUFFERED=1` — **without this, Python's `print()` output can
  get buffered and never show up in `docker logs` in real time** (the
  process is actually running fine, it just looks stuck — a common false
  alarm),
- installing dependencies via `uv sync --frozen --no-dev` before copying the
  rest of the code (layer caching — a rebuild triggered by a code-only
  change, with no dependency change, stays fast).

Key element of `compose.yaml` — the `develop.watch` section:

- `action: sync` for the source code directory (file change → synced into
  the running container, no rebuild needed),
- `ignore: .venv/` — the local `.venv` (Windows) has no reason to be synced
  into the container (different platform; the image creates its own),
- `action: rebuild` for `pyproject.toml`/`uv.lock` — a dependency change
  requires a full image rebuild, not just a file sync.

## 10. Running it

With watch (the dev loop — code changes sync live):

```bash
docker compose up --watch
```

Without watch (plain run, no auto-sync):

```bash
docker compose up
```

Force a full image rebuild:

```bash
docker compose up --watch --build
```

Logs in a separate terminal (handy with the interactive watch TUI, which by
default overwrites the last line with a status message):

```bash
docker compose logs -f
```

## 11. GPIO and I2C peripherals (e.g. an LCD display)

Physical GPIO/I2C access needs setup on two separate layers: the Pi's host
OS (kernel-level, one-time) and the container (device access, one-time
compose config). This applies to any GPIO peripheral (LEDs, buttons,
buzzers) and any I2C peripheral (LCDs, sensors, RTC modules, etc.).

### GPIO — high-level library

Use **`gpiozero`** for GPIO, not the classic `RPi.GPIO`:

```bash
uv add gpiozero
```

> **Pi 5 note:** `RPi.GPIO` does not support Pi 5's GPIO chip (RP1) at all.
> `gpiozero` is the Raspberry Pi Foundation's own high-level library and
> picks the correct low-level backend automatically.

`gpiozero` itself is only the high-level API — it still needs a low-level
"pin factory" backend to actually talk to hardware. On Pi 5 that's
**`lgpio`**. Without it, any GPIO object (`LED(17)`, etc.) raises
`gpiozero.exc.BadPinFactory: Unable to load any default pin factory!` at
runtime.

```bash
uv add "lgpio; sys_platform == 'linux'"
```

The `sys_platform == 'linux'` marker keeps this out of the local Windows
`.venv` (it needs a Linux GPIO character device and a C compiler to build —
neither applies on Windows, and it isn't imported directly in application
code anyway, so skipping it locally causes no IDE issues).

`lgpio` is a C extension and may not have a prebuilt wheel for every
platform, so the Dockerfile needs build tools available before `uv sync`:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
```

### I2C — enabling the bus on the host

I2C is disabled by default on Raspberry Pi OS. This is a host-level kernel
setting — it cannot be done from inside a container. Over SSH, on the Pi:

```bash
sudo raspi-config nonint do_i2c 0
```

```bash
sudo reboot
```

Verify the device node exists:

```bash
ls /dev/i2c*
```

Should list `/dev/i2c-1`. Install `i2c-tools` and scan the bus to find a
connected device's address (e.g. an LCD's PCF8574 I2C backpack — typically
`0x27` or `0x3f`):

```bash
sudo apt install -y i2c-tools
```

```bash
i2cdetect -y 1
```

### Container device access

Both GPIO and I2C device nodes under `/dev` need to be reachable from
inside the container. The simplest approach for local development is
running the container in privileged mode, which grants access to the
host's entire `/dev` (exact device-node numbering, e.g. which `gpiochipN`
maps to the header pins, varies with kernel/OS version on Pi 5, so this
avoids having to pin one down):

```yaml
services:
  rpi-edge:
    build: .
    privileged: true
```

### I2C peripheral libraries (example: an HD44780 LCD via PCF8574)

```bash
uv add rplcd
```

```bash
uv add "smbus2; sys_platform == 'linux'"
```

`smbus2` is the low-level library `RPLCD`'s I2C mode is built on; it relies
on the Linux-only `fcntl` module, so it's marked Linux-only the same way as
`lgpio`. `RPLCD` itself is pure Python with no compiled extensions, so
unlike `lgpio`/`smbus2` it's left **without** a platform marker — installing
it locally on Windows too is harmless (it will never actually be run there)
and keeps the IDE able to resolve `from RPLCD.i2c import CharLCD` instead of
underlining it as an unresolved import.

```python
from RPLCD.i2c import CharLCD

lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,       # from i2cdetect
    port=1,              # /dev/i2c-1
    cols=20, rows=4,      # match your display's actual size
    dotsize=8,
    charmap='A02',
    auto_linebreaks=True,
)
lcd.write_string('Hello RPi!')
```

## Troubleshooting

**`permission denied` on `docker run` despite being added to the `docker`
group.** Check whether `usermod -aG docker` actually got the right username
(see the pitfall in step 4), then `sudo reboot` and reconnect fresh.

**`.local` stops resolving (`Could not resolve hostname` error).** Common
after installing WSL, or after a hotspot has been running for a while. As a
quick fix: find the Pi's current IP and connect to it directly. Long-term:
set up an alias in `~/.ssh/config` with a hardcoded IP (step 5) and update
the Docker context (`docker context update rpi --docker "host=ssh://<alias>"`),
or give the Pi a static IP (`nmcli connection modify ... ipv4.method manual`).

**Container looks stuck, no logs after startup.** Check whether the process
is actually running (`docker top <container>`) before assuming it's hung —
the most common cause is Python stdout buffering (missing
`PYTHONUNBUFFERED=1`, see step 9), not a real hang.

**Build fails with `Failed to spawn: <file>.py` / `No such file or
directory`.** Usually means the image was built before the entrypoint file
was actually saved to disk. Force a fresh build:
`docker compose up --watch --build`.

**Container has no internet/DNS access.** Check from inside it:

```bash
docker exec <container> python3 -c "import socket; print(socket.gethostbyname('pypi.org'))"
```

If that fails, the issue is in routing/NAT on the Pi side (e.g. missing
`ip_forward`), not in the project itself.

**`gpiozero.exc.BadPinFactory: Unable to load any default pin factory!`**
No low-level GPIO backend is installed (`lgpio`, `RPi.GPIO`, `pigpio`) — see
section 11. On Pi 5, install `lgpio`. Also make sure the container has
device access (`privileged: true`).

**LCD backlight is on but no text is visible (and no exception was
raised).** Almost always the contrast potentiometer on the back of the
PCF8574 I2C backpack, not a code issue — a successful `CharLCD(...)` call
with no error already confirms I2C communication is working. Turn the
small trimmer potentiometer slowly through its full range with a
screwdriver while the script is running; the readable range is often
narrow.
