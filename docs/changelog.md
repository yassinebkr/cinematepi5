# Changelog

Release notes for Cinemate. For downloads, see the [releases page](https://github.com/Tiramisioux/cinemate/releases).


## Local development state - 2026-09-20

This section describes the running local IMX283 / Raspberry Pi 5 camera and is not an upstream release tag.

- Added guided ICM-42688 calibration: stationary gyro bias, multi-orientation accelerometer fit, six-face camera-frame alignment, persistent versioned calibration and separate operator horizon zero.
- Added a full-screen HDMI calibration UI with a rotating triangulated 3D coverage sphere and browser-driven calibration controls.
- Added a central preview invariant so active calibration always forces the cinepi-raw DRM plane off, including after camera/Cinemate restarts.
- Replaced the slow NumPy 1920 x 1080 RGB565 framebuffer conversion with a byte-equivalent single-threaded OpenCV path and raised SimpleGUI from 12 to 30 FPS.
- Validated 3936 x 2176 12-bit RAW at approximately 33 FPS with HDMI preview and 30 FPS GUI: 0 camera-frame drops, 0 write failures, low RAM-buffer occupancy and substantial remaining RAM.
- Added Phase B low-latency LEVEL and cinematography-oriented SHAKE filtering.
- Stabilized the HDMI LEVEL presentation around zero with a display-only < 0.05° roll snap shared by the numeric readout and horizon-line geometry, removing sign/sub-pixel line flicker without modifying IMU telemetry or SHAKE.
- Added renderer-level regression tests for near-zero, threshold, large signed roll and non-zero/saturated SHAKE cases.
- Increased Pi 5 I2C1 from 100 kHz to 400 kHz for the 1 kHz ICM-42688 FIFO; measured live IMU publication improved from approximately 5 Hz to approximately 30.5 Hz.
- Investigated historical throttled=0x50000. A clean reboot and full RAW stress test with the USB-powered HDMI monitor attached remained at throttled=0x0; official 27 W PSU negotiation is 5 V / 5 A and no USB over-current was detected.

See [IMU calibration, HDMI preview and live HUD](imu-calibration-and-live-hud.md) for implementation details and measurements.

## Version 3.3.2

### libcamera

- Cinemate now uses its own fork of libcamera.

### imx283 driver

- Cinemate now uses its own fork of imx283 driver.
- 2 additional modes: 3840 x 2160 (4K UHD, native crop) and 2736 x 1538 (2.7K 16:9, binned) 

### imx585 driver

- Cinemate now uses its own fork of imx283 driver.

### CinePi-RAW recorder

- **Frame-rate phase lock** — closed-loop control (sigma-delta VBLANK dither) keeps long takes locked to the Pi's wall clock and pre-converges during preview. On by default.
- **More reliable audio sync on 4K / exFAT** — the capture path was reworked (protected helper, dedicated writer thread, wall-clock reconciliation, real-time scheduling) for more reliable WAV sync on demanding modes.
- **Wall clock embedded timecode** — timecode is anchored to the first frame's wall-clock time and follows the Pi's real-time clock, so it reflects the actual time of day rather than a plain sequential frame count; routed per camera for dual-sensor rigs.
- **Correct Pi 4 RAW** — CSI2-packed frames decode correctly on Pi 4-family boards; raw packing (P/U) is chosen per Pi model automatically.
- **Camera model** — set the camera model manually for each attached sensor.

### Cinemate

- **Storage / media** — multi-drive RAW hot-swap with a standby drive and automatic promotion. Default format is exFAT.

### Raspberry Pi / Bookworm**
- **Boot / install** — faster boot-to-preview on Pi 4/5 (about 10-15 seconds)

## Version 3.3.1

### CinePi-RAW recorder

- New Cinemate fork, reducing CPU load and temperature dramatically and reducing dropped frames.
- Resolution can now be changed without restarting the recorder process, enabling faster mode changes and dynamic resolution switching.
- Better USB microphone sync.

### Cinemate workflow

- exFAT support and filesystem-aware storage profiles for efficient media writes, including IMX585 25 fps at 4K to SSD without frame drops.
- Dynamic resolution switching to match the observed sustainable frame rate for the attached sensor and storage media — for example, IMX585 automatically switches to HD above 25 fps when an SSD is used.
- Hot-swapping between 16-bit and 24-bit USB microphones.
- 4K-class recording modes are visible by default.
- Automatic storage pre-roll can be disabled in `settings.json`.

### Local web UI / monitoring update - 2026-09-20

- Reworked Live, Clips and Offload layouts for phone, tablet and desktop portrait/landscape use.
- Added safe-area/dynamic-viewport handling for mobile browsers.
- Replaced duplicate touch/click fullscreen logic with one direct user-gesture Fullscreen API path.
- Added manifest, Home Screen metadata, app icons and service-worker shell.
- Added fullscreen controls to Clips and Offload.
- Made MJPEG JPEG quality configurable in cinepi-raw.
- Made lores preview-height cap configurable in settings.json.
- Changed stream URL generation to follow the hostname/IP used by the browser.
- Intermediate web-preview profiles were stress-tested under simultaneous RAW recording.
- The retained profile is 1446 x 800 / JPEG Q80 at approximately 33 FPS.
- Reset-aware simultaneous 3936 x 2176 12-bit RAW + active MJPEG test: 0 drops, 0 write failures.

## Local web UI / preview update - 2026-09-20

- Reworked live camera UI for responsive desktop, phone and tablet layouts.
- Portrait mode now uses the black space below the wide camera preview for wrapped monitor controls instead of leaving a large dead region.
- Landscape phone/tablet mode now defaults to a clean monitor view with retractable translucent control overlays.
- Changed desktop tool rail from layout-consuming sidebar to preview overlay.
- Added shared responsive CSS and viewport/safe-area handling for Live, Clips and Offload.
- Added web-app manifest, service worker shell and Home Screen icons.
- Replaced conflicting fullscreen click/touch/delayed-reentry logic with a direct gesture-based controller and persistent floating Exit Fullscreen button on supported browsers.
- Treat iOS/iPadOS Home Screen standalone mode as the reliable full-screen workflow and hide the redundant fullscreen button there.
- Improved Clips portrait layout and Offload portrait layout.
- Validated web-preview tuning experimentally. Final conservative profile is 1446 x 800 JPEG Q80 at approximately 33 FPS.
- Final simultaneous RAW + active MJPEG test at 3936 x 2176 12-bit / 33 FPS produced zero dropped frames and zero write failures after per-take counter reset.

### Web preview / responsive controller follow-up

Local 2026-09-20 development:

- Added shared responsive camera/Clips/Offload styles with phone/tablet portrait and landscape handling.
- Added collapsible camera controls for compact landscape monitoring.
- Reworked browser fullscreen handling to avoid duplicate touch/click requests; added explicit fullscreen exit control where the API is available.
- Added PWA manifest, service worker shell and Home Screen icons. iPhone/iPad Home Screen mode is the preferred full-screen workflow.
- Set the validated web-preview profile to 1446 x 800, JPEG quality 80, approximately 33 fps.
- Added Clips REC indicator/timecode through a lightweight in-process state endpoint.
- Added automatic Clips page refresh only after REC has stopped and recording buffers/writers are fully finalized.
- Explicitly deferred live camera preview inside Clips.
- Final long validation with a continuous MJPEG consumer: 30 s / 999 DNG and 40 s / 1333 DNG at 3936 x 2176 12-bit 33 fps, both with 0 DNG sequence drops and 0 write failures.
- Documented a separate storage-state-dependent sustained-write collapse observed in earlier tests; it reproduced without MJPEG and therefore is not attributed to the web preview.

See [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md).

### Canonical REC indicator synchronization

- Replaced the red recording background/border treatment with a dedicated blinking REC dot.
- Standardized user-facing recording indication on Redis is_recording.
- Added recording to Camera Socket.IO initial state, fixing navigation to Camera while a take is already in progress.
- Added recording_state Socket.IO start/stop pushes.
- Added shared /recording-state HTTP endpoint with /clips/recording-state compatibility alias.
- Added a 1-second Camera fallback poll for navigation/reconnect recovery.
- Added responsive Web REC-dot placement: right-side desktop, top-right portrait, top-left compact landscape.
- Added HDMI REC dot independent of the LEVEL HUD toggle.
- Preserved blue preroll/transient background as a separate non-REC state.
- Verified a real start -> navigate/open Camera while recording -> stop sequence with synchronized Redis, Camera, Clips and HDMI framebuffer state.

### Clips REC timer readability

- Changed the Clips REC elapsed-time display from full HH:MM:SS:FF timecode to operator-friendly M:SS.
- Kept the 500 ms recording-state poll for responsive start/stop indication.
- Limited visible timer updates to one change per elapsed second.
- Retained the complete HH:MM:SS:FF timecode in the recording-state API for diagnostics.

### Clips timer race and mobile camera layout

- Fixed a Clips REC timer race where a new take could briefly display the previous take duration before returning to 0:00.
- Added a per-take monotonic elapsed-time latch: new takes visually start at 0:00, stale values are ignored until timer reset is observed, and the display never moves backward within a take.
- Verified two consecutive takes including a second start with approximately 4.56 seconds of stale recording_time; visible sequence remained 0:00 -> 0:01 -> 0:02 -> 0:03 -> 0:04.
- Moved the real LUT selector into the portrait top bar immediately left of Clips.
- Moved TAG into the portrait tool row and sized it like the other monitoring controls.
- Repositioned the portrait Web REC dot from the actual displayed image rectangle.
- Offset the compact-landscape Clips control left of the retractable X/menu button to avoid overlap.
- Bumped shared responsive/PWA assets to revision 20260920f / service-worker shell v5.

### Clips background proxy progress, independent LUT and mobile layout follow-up

- Replaced blocking proxy-generation overlay with a per-clip inline progress bar.
- Proxy rendering now continues in the background without taking control of the current player.
- Added detailed proxy states: queued, rendering percentage, paused while recording, verifying, ready and error.
- Validated real proxy progress on a 10-DNG clip through queued -> encoding -> verifying -> ready.
- Confirmed queue-position reporting when a second render waits behind an active one.
- Added independent per-clip LUT/look selection in Clips using clipLuts storage.
- Kept Camera live-preview LUT state completely separate.
- Fixed live-stream reconstruction to use window.location.hostname:8000 rather than a client-side localhost address.
- Added MJPEG reconnect handling for page return, visibility restoration and network restoration without creating WebKit retry loops.
- Refined portrait Camera centering and REC-dot geometry.
- Restored compact-landscape scope overlays for HIST/WAVE/VECT.
- Offset compact-landscape Clips control away from the retractable close/menu button.
- Anchored compact-landscape REC indicator safely inside the viewport.
- Bumped shared UI assets to revision 20260920l and service-worker shell v12.
