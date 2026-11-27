# LEDs, buzzer, LCD and faults

What the in-car hardware of the edge node shows: what each LED means and when it is on or blinks, what the buzzer
says, which faults exist, when each one appears and when it goes away. The detection mode comes first, the
collection mode is at the end. Wiring and pins: [RASPBERRY_PI_SETUP.md](RASPBERRY_PI_SETUP.md#pins-in-use).

Code: the LEDs, the switches and the buzzer are `common/peripherals.py`; the faults are listed in
`common/fault_catalog.py` (a test keeps this document and that list in step) and work as `common/faults.py`
describes.

## 1. Faults in general

A **fault** is a lasting condition that keeps the device from its job (reading plates, sending them, raising
alerts) or puts data at risk, and that someone has to know about or act on. A fault:

- lights the red **fault** LED (steady) for as long as it lasts;
- is listed on the **FAULTS** page of the LCD (one per row, `+N more` below three);
- sounds the buzzer once, a continuous tone of **3 s**, when it appears. A fault that comes back within 10 minutes
  of its last tone is not sounded again, so a flapping one does not keep beeping;
- is logged once when it appears (`fault_raised`, with `code` and `text`) and once when it goes away
  (`fault_cleared`). The details are in the log event of the cause, named in the tables below.

**Not a fault:** what recovers by itself and has its own LED (no network: net LED; no GPS fix: gps LED; data
waiting to be sent: queue LED), a single event that passes (one failed request, one timeout, one photo not saved
because the encoder was busy), an alert (alert LED), the analysis stopped with the run switch, the models being
downloaded, rows refused before the mode started, the USB stick not being in the port.

**Retried things** (requests to the platform, the frame loop) light their fault only after **3 failures in a
row**; one success clears it and starts the count again. An attempt without any answer (no network) neither counts
nor breaks the count: the network LED shows it.

**Counted losses** (data dropped, refused items) show the number lost since the mode started and stay until the
next start of the mode (a restart of the container or a switch of the mode).

## 2. Detection mode

### LEDs

| LED (GPIO) | Colour | On | Blinking (1 Hz) | Off |
|---|---|---|---|---|
| run (5) | green | | frames are analysed | analysis stopped with the run switch, waiting for the configuration or the models, or the frame loop failing |
| net (6) | green | the platform answers (any HTTP answer) | no answer: the data waits in the queues on the SD card | no request yet, or the sign-in is refused (no token) |
| gps (13) | green | a fix young enough for the frames (`gps.maxFixAgeSeconds`) | no such fix: no plate is read until there is one | no data from a module |
| queue (19) | yellow | plates or track points wait to be sent | only photos wait (they go when the link is free) | nothing waits |
| alert (26) | red | an alert since the analysis started | an alert is on the screen (15 s) | no alert since the analysis started |
| fault (12) | red | at least one fault (section 2, Faults) | | no fault |

The alert LED needs no acknowledgement: a short press of the run switch (stop) or a switch of the mode turns it off.

### Buzzer

| Sound | When |
|---|---|
| 1 short beep | the first frame of the mode is analysed; the analysis is started with the run switch |
| 2 short beeps | the analysis is stopped with the run switch |
| 3 beeps of 0.4 s | an accepted plate is on the alert list |
| 2 beeps of 0.3 s | the mode is switched (long press of the run switch) |
| 3 s tone | a fault appears |

### Switches

| Switch (GPIO) | Short press | Long press (2 s) |
|---|---|---|
| run (22) | stop / start the analysis: the camera closes, the queues go on being sent | switch to the collection mode |
| page (23) | next LCD page | back to the home page |

### LCD pages

| Page | Shows |
|---|---|
| home | `DETECTING` and frames per second (or `DETECTION STOPPED`, `WAITING FOR CONFIG / MODELS`); `network` ok, offline, connecting, no sign-in, denied; `GPS` 3D fix, 2D fix, no fix, no data; `unsent plates` |
| GPS 2/6 | the fix and its age, satellites used of those in view, accuracy, speed |
| WAITING TO SEND 3/6 | plates, track points and photos waiting to be sent |
| FAULTS 4/6 | the faults, one per row |
| SYSTEM 5/6 | the configuration version, IP, CPU temperature, the model versions, free space on the SD card |
| LAST PLATES 6/6 | the last two plates accepted for sending (`ALERT` when on the list) and how long ago; the plates on the alert list (`loading` before the first list) |

An alert replaces whichever page shows for 15 s: `*** ALERT ***`, the plate and the alert text.

### Faults

| LCD text | Code | Appears when | Goes away when | What to do | Log |
|---|---|---|---|---|---|
| no configuration | `no_config` | a poll ended and the device has no configuration at all (none received, no copy on the SD card): it does not start the camera | a configuration is taken | check the network and that the device exists in device-management | `config_poll_failed`, `configuration_missing` |
| config refused | `config_refused` | the configuration of device-management is outside the contract of the device; the device keeps the one it runs | a valid configuration is taken | deploy matching versions of device-management and rpi-edge | `configuration_refused` (the fields) |
| config poll failed | `config_poll_failed` | 3 error answers in a row to `GET /api/v1/device/config` (429, 5xx, a wrong URL): the device runs on its copy, but no change arrives | a poll answers 200 or 304 | check device-management (ECS tasks) and `API_BASE_URL` | `config_poll_failed` (status) |
| no credentials | `no_credentials` | the credentials file of the device is missing or unreadable | a request gets a token | put the credentials on the Pi (`infrastructure/scripts/README.md`) | `batch_not_sent`, `config_poll_failed` (error) |
| sign-in refused | `sign_in_refused` | Cognito refuses the sign-in: wrong password, unknown user, unknown app client (`COGNITO_CLIENT_ID`) | a request gets a token | check the device account and `COGNITO_CLIENT_ID` | as above |
| token refused (401) | `token_refused` | the gateway refuses the token even after a renewal (a token of another app client or user pool) | that endpoint answers with success | check `COGNITO_CLIENT_ID` and `COGNITO_REGION` against the environment | `access_token_refused` |
| not a device token | `not_device_token` | 403 FORBIDDEN: the token is valid but not of a device account | that endpoint answers with success | the credentials belong to a person, not to the device | `batch_forbidden`, `image_urls_forbidden` |
| device not found | `device_not_found` | 404 DEVICE_NOT_FOUND from device-management: the device was deleted, or belongs to another environment | that endpoint answers with success | register the device again (`create_device.py`) and put its new credentials on the Pi | `config_poll_failed` (code) |
| device has no owner | `no_owner` | 403 DEVICE_NOT_PAIRED from `GET /api/v1/alerts`: no person owns the device, so it has no alert list | the alert list answers with success | pair the device with an account | `alert_poll_failed` (code) |
| no models | `no_models` | an update failed and the device has no models at all: it cannot detect | the configured versions run | check the network and the models bucket | `models_update_failed` |
| model not published | `model_not_published` | 409 MODEL_NOT_PUBLISHED: the configuration names a model version that is not in the models bucket | the configured versions run | publish it (`anpr-publish-model`) or set a published version in the configuration | `models_update_failed` (error) |
| models not updated | `models_not_updated` | 3 failed updates in a row with an answer (an error status, an expired download URL, a damaged file) while an older set runs | the configured versions run | check device-management and the models bucket | `models_update_failed` |
| model load failed | `model_load_failed` | a downloaded or cached set does not load (ONNX Runtime refuses it) | the configured versions run | check the export of the model (ml-models) | `models_update_error`, `models_load_error` |
| plates not sent | `plates_not_sent` | 3 error answers in a row to `POST /api/v1/ingest/detections` (429, 5xx, a wrong URL); the plates wait in the queue | a batch is accepted | check the ingest Lambda and the gateway | `batch_failed` (status) |
| track not sent | `track_not_sent` | the same for `POST /api/v1/ingest/device-locations` | a batch is accepted | as above | `batch_failed` |
| metrics not sent | `metrics_not_sent` | the same for `POST /api/v1/device/metrics`; the device shows offline in the application | a batch is accepted | check device-management | `batch_failed` |
| photos not sent | `photos_not_sent` | 3 failures in a row of the photos: error answers for the presigned URLs, an invalid answer, or an S3 PUT refused | a batch of photos is uploaded | check device-management and the photos bucket | `image_urls_failed`, `image_urls_invalid`, `image_not_uploaded` |
| refused items N | `refused_items` | the platform refused N items for good (400, 413, 415) since the mode started; they are kept in the quarantine of the queue for diagnosis | the next start of the mode | read the field codes in the log (a wrong clock, a contract out of step) | `items_quarantined`, `images_quarantined` |
| data dropped N | `data_dropped` | the retention deleted N plates or track points that were never sent (30 days without sending, or the row limit) | the next start of the mode | the data is lost; find why nothing was sent | `items_dropped` |
| alert list failed | `alert_list_failed` | 3 error answers in a row to `GET /api/v1/alerts`: no alert is raised, or only those of an old list | the list answers 200 or 304 | check operations-service (ECS tasks) | `alert_poll_failed` (status) |
| alert list invalid | `alert_list_invalid` | the alert list is outside the contract of the device | a valid list is taken (200 or 304) | deploy matching versions of operations-service and rpi-edge | `alert_list_refused` |
| frame loop error | `frame_loop_failed` | 3 failures of the frame loop in a row (camera, models); it retries every 5 s | a frame goes through | check the camera cable; the log has the error | `detection_loop_error` |
| GPS not configured | `gps_not_configured` | neither `GPS_DEVICE` nor `GPS_FIXED_LOCATION` is set: no frame gets a position, no plate is read | the container starts with one of them | set `GPS_DEVICE` in `rpi-edge/.env` | `gps_not_configured` |
| GPS module silent | `gps_silent` | `GPS_DEVICE` is set but no sentence has arrived for 60 s | a sentence arrives | check the wiring, the power of the module and the UART (`/dev/ttyAMA0`) | `gps_unavailable` |
| clock wrong by Ns | `clock_wrong` | the clock of the Pi differs from GPS time by 5 s or more: the platform refuses what is stamped with it | the clock agrees with GPS time | let the Pi synchronise its clock (NTP, needs the network) | `clock_skew` |
| SD card low NMB | `sd_low` | less than 1 GB is free on the SD card (queues, photos, models) | more is free again | free space on the card | |
| power too low | `undervoltage` | the Pi reports under-voltage now | the voltage is back | use a proper supply (27 W) and cable | |
| CPU throttled | `throttled` | the Pi slows its CPU down now (heat or power) | it runs at full speed again | cool the Pi, check the supply | |
| CPU hot NC | `cpu_hot` | the CPU is at 80 °C or more (the Pi 5 throttles from 85 °C) | it is below 80 °C | shade or cool the Pi | |

### Answers of the platform

What the device does with each answer, and which fault it can lead to. Every request goes through API Gateway,
which validates the token; the services answer with RFC 9457 problem documents whose `code` decides where the
gateway's own answers (401, 429, 503, 504) have no such body.

| Answer | Endpoints | Device does | Fault |
|---|---|---|---|
| 200, 202, 204 | all | takes the answer, deletes what was sent | clears the fault of that endpoint |
| 304 | config, alerts | keeps what it has | clears the fault of that endpoint |
| 400, 413, 415 | ingest, metrics, photo URLs | quarantines the items the error names (or the batch), sends the rest again | refused items |
| 400 | alerts (a malformed request) | keeps the list, tries again | alert list failed (after 3) |
| 401 | all (gateway) | renews the token and tries once more; a second 401 is kept | token refused (401) |
| 403 DEVICE_NOT_PAIRED | alerts | keeps the list it has | device has no owner |
| 403 FORBIDDEN, other 403 | all | keeps the data, waits 10 min before the stream tries again | not a device token |
| 404 DEVICE_NOT_FOUND | config, models, metrics, photo URLs | keeps the data, tries again | device not found |
| 404 without a code (no such route) | all | keeps the data, backs off | the fault of the endpoint (after 3) |
| 409 MODEL_NOT_PUBLISHED | models | runs the set it has, tries again | model not published |
| 429, 500, 502, 503, 504 | all | keeps the data, backs off (honours `Retry-After`) | the fault of the endpoint (after 3) |
| S3 403, 404, 5xx | photo PUT, model download (presigned URLs) | keeps the file, asks for fresh URLs next time | photos not sent / models not updated (after 3) |
| Cognito NotAuthorized, UserNotFound, ResourceNotFound, PasswordResetRequired, UserNotConfirmed, InvalidParameter | sign-in | no token until the setup is fixed | sign-in refused |
| Cognito TooManyRequests, InternalError, 5xx | sign-in | treated as no answer | none (net LED) |
| no answer (timeout, DNS, no route) | all | keeps the data, backs off | none (net LED) |

## 3. Collection mode

Everything that is not listed here stays off in this mode: net and gps are not used.

### LEDs

| LED (GPIO) | Colour | On | Blinking (1 Hz) | Off |
|---|---|---|---|---|
| run (5) | green | | the camera runs | the camera does not run |
| queue (19) | yellow | | less than 5 GB free on the USB stick (recording stops at `recording.min_free_mb`) | enough space, or no stick |
| alert (26) | red | recording | | not recording |
| fault (12) | red | at least one fault | | no fault |

### Buzzer and switches

| | |
|---|---|
| run switch (22), short press | start recording (1 beep) / stop recording (2 beeps); 1 long beep: it failed (no stick, no space, camera not running) |
| run switch (22), long press (2 s) | switch to the detection mode (2 beeps of 0.3 s; recording stops and the stick is ejected first) |
| page switch (23) | next page (home, FAULTS 2/2); a long press: home |
| 3 s tone | a fault appears |

The home page shows `REC frames` and the frames saved (or `IDLE` and the frame rate set), the free space on the
USB stick, the exposure (shutter and ISO), the IP address of the web UI and the CPU temperature.

### Faults

| LCD text | Code | Appears when | Goes away when | What to do | Log |
|---|---|---|---|---|---|
| camera error | `camera_error` | the camera does not open or stopped (it is retried every 5 s) | the camera runs | check the camera cable; the web UI shows the error | `camera_open_failed` |
| dropped frames N | `dropped_frames` | the recording dropped N frames (the encoder or the stick is too slow) | the recording stops | lower the frame rate or use a faster stick | `recording_stopped` (dropped) |
| USB error | `usb_error` | a stick is in the port but cannot be used: mounting failed, it is read-only or damaged, unmounting failed | the stick works or is pulled out | check the stick on a PC (chkdsk), try another one | `usb_mount_failed`, `usb_not_writable`, `usb_eject_failed` |
| power too low | `undervoltage` | as in the detection mode | | | |
| CPU throttled | `throttled` | as in the detection mode | | | |
| CPU hot NC | `cpu_hot` | as in the detection mode | | | |
