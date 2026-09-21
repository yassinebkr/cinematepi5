# Web GUI

Cinemate includes a small Flask + Socket.IO web interface that mirrors the live preview and exposes the main camera controls in a browser.

- the control UI listens on port `5000`, with the URL `http://cinepi.local:5000/`.
- the clean MJPEG preview stream is available on port `8000` with the URL `http://cinepi.local:8000/stream`.

The browser UI exposes:

- ISO, shutter angle, FPS, white balance, and resolution selectors
- live preview from the MJPEG stream
- tap/click on the preview area to toggle REC
- storage unmount button
- fullscreen toggle
- live stats such as free space, write speed, buffered frames, buffer size, CPU load, RAM load, temperature, and exposure time

!!! note ""

    When using dual sensors, the second camera's preview stream is served on port `8001`. The control UI stays on port `5000`.

## IMU calibration controls

The LEVEL panel on the local camera also contains the guided IMU calibration controls.

- IMU CALIBRATION starts the HDMI full-screen wizard.
- CONTINUE advances the active stage.
- CANCEL exits without replacing the saved calibration.
- set zero changes only the operator horizon reference; it does not rewrite the physical IMU calibration.

The control UI is plain HTTP. Use http://cinepi.local:5000/ or the Pi IP with port 5000. Do not use HTTPS on this port.

When calibration is active, the cinepi-raw DRM preview plane is forcibly disabled so it cannot cover the full-screen calibration framebuffer. This rule is enforced centrally in CinePiManager and therefore also applies after restarts.

## Responsive web application shell - local 2026-09-20

The local IMX283/Pi 5 camera now uses a common responsive shell for the live camera, Clips and Offload pages.

Shared assets:

    src/module/app/static/css/cinemate-responsive.css
    src/module/app/static/js/cinemate-app.js
    src/module/app/static/manifest.webmanifest
    src/module/app/static/sw.js

All pages use viewport-fit=cover and CSS safe-area insets for notched iPhones/iPads.

### Live camera layout

The live view now adapts to the viewport instead of assuming a desktop canvas.

Desktop / wide landscape:

- camera tools remain in a vertical rail
- the preview uses the remaining width
- top and bottom status bars remain compact

Phone/tablet portrait or narrow landscape:

- preview uses the full available width
- camera tools become a horizontal scrollable monitor bar
- bottom telemetry uses a responsive grid
- dynamic viewport units and safe-area insets are used
- the page should not require manual browser zoom-out

The MJPEG URL now uses the same hostname/IP used by the browser. Opening the UI by IP therefore produces an IP-based stream URL instead of forcing cinepi.local.

### Clips orientation behavior

Clips is deliberately orientation-aware.

Landscape / desktop:

- proxy player and clip list are side by side

Portrait / narrow tablet:

- the proxy player uses the full width with a 16:9 aspect ratio
- the clip list moves below it
- thumbnails become larger relative to the screen
- metadata/actions wrap below the clip title instead of forcing a wide row
- filters and header controls wrap to available width

This makes reviewing previous takes particularly comfortable in portrait while retaining an efficient landscape layout.

### Offload orientation behavior

Offload also changes layout according to orientation.

Portrait:

- header controls wrap into touch-friendly rows
- each clip becomes a compact two-row grid
- name/size stay readable without horizontal page zoom
- backup state is displayed below the main clip row

Landscape/desktop keeps the denser horizontal list.

### Fullscreen

The old implementation fired both touchstart and click and also attempted delayed requestFullscreen calls. Those paths were removed.

The common implementation now:

- invokes fullscreen from one direct click gesture
- awaits the standard Fullscreen API when available
- supports webkit fullscreen where exposed
- tracks real fullscreen state through fullscreenchange
- does not attempt delayed automatic re-entry
- falls back to Home Screen instructions when browser fullscreen is unavailable

Clips and Offload now expose the same fullscreen control as the live page.

### PWA / Home Screen

The local UI now includes:

- web app manifest
- 192 px and 512 px icons
- Apple touch icon
- display=fullscreen with standalone fallback
- orientation=any
- Apple mobile web app metadata
- root-scope service-worker route

iOS/iPadOS can use the Home Screen web-app metadata for a browserless launch.

Important: Android installability as a true PWA still requires a secure context. The current LAN UI is plain HTTP, so the manifest/shell is ready but a trusted local HTTPS endpoint is still required to guarantee a standalone installed PWA on Android/Chromium-family browsers.

Do not silently replace port 5000 with TLS: the MJPEG stream on port 8000 also has to be placed behind the same trusted HTTPS origin to avoid mixed-content blocking. A reverse proxy is the appropriate future architecture.

## Validated web preview quality profile

The original web preview was:

- 1302 x 720
- JPEG quality hardcoded at 60
- approximately 50 kB/frame
- approximately 13.3 Mbit/s
- approximately 33 FPS

The MJPEG quality is now configurable in settings.json and passed through post-processing JSON to cinepi-raw.

Two higher profiles were rejected after RAW stress testing:

- 1732 x 958 / Q85: visually high quality but caused camera-frame drops during full-resolution RAW recording
- approximately 1598 x 884 / Q80: much better, but still produced one drop in the 12-second stress test

Validated production profile:

- 1446 x 800
- JPEG quality 78
- approximately 33.08 FPS idle
- approximately 118 kB/frame in the measured scene
- approximately 31.2 Mbit/s in the measured scene

A 12-second 3936 x 2176 12-bit RAW recording with a real MJPEG client connected measured:

- RAW cadence approximately 32.9998 FPS
- 0 dropped camera frames
- 0 write failures
- max recording bufferSize 5
- max bufferSizeMax 6
- max framesInFlight 8
- minimum MemAvailable approximately 2.97 GiB
- maximum temperature approximately 58.4 C
- get_throttled remained 0x0

The web profile must remain subordinate to RAW reliability. Any future increase in quality/resolution requires the same simultaneous RAW + MJPEG stress test.

## Responsive live UI / PWA state (local 2026-09-20)

The local IMX283/Pi 5 camera UI now uses a shared responsive shell for the live camera, Clips and Offload pages.

### Live camera layout

Desktop:

- the MJPEG image owns the full preview canvas width
- the monitor/tool rail overlays the image rather than subtracting a fixed 136 px from the preview
- the top and bottom information bars remain compact
- Fullscreen API uses a single user-gesture handler
- a floating Exit Fullscreen control is created while browser fullscreen is active

Portrait phone/tablet:

- camera preview is kept at its natural wide aspect near the top
- the remaining black area below the image is used by monitor tools instead of leaving a large dead gap
- LOOK/HIST/WAVE/VECT/ZEBRA/PEAK/LEVEL/TAG controls wrap instead of being truncated
- status controls use a responsive grid
- LEVEL overlay geometry is re-centered from the actual stream element after resize/orientation changes

Landscape phone/tablet:

- the camera image occupies the entire viewport
- controls are collapsed by default
- a small UI button toggles translucent top/tool/bottom overlays
- this avoids losing a large fraction of the picture to permanent control bars

Clips:

- landscape uses a video/list split
- portrait stacks filters, video preview and clip list
- portrait thumbnails grow for easier review and metadata/actions wrap below them

Offload:

- controls wrap in portrait
- each clip becomes a compact two-row grid with name/size/status
- landscape retains the denser desktop list

### PWA / fullscreen

Shared assets:

    src/module/app/static/manifest.webmanifest
    src/module/app/static/sw.js
    src/module/app/static/js/cinemate-app.js
    src/module/app/static/css/cinemate-responsive.css

The manifest uses a fullscreen/standalone display profile and includes 192 px, 512 px and Apple touch icons.

On iPhone/iPad, arbitrary page fullscreen is not treated as a dependable control path. The button therefore explains that the correct browserless mode is Add to Home Screen. When launched from the Home Screen, the redundant fullscreen button is hidden.

On browsers that expose the Fullscreen API, Enter Fullscreen is triggered only from the direct click gesture. While fullscreen is active, a floating Exit Fullscreen button remains accessible.

Old click/touchstart double-handlers and delayed automatic re-entry hacks were removed.

The UI is still served over plain HTTP on port 5000. Android PWA install behavior may therefore vary by browser because full installability normally expects HTTPS.

### Web preview quality profile

The MJPEG lores size and quality are configurable through:

    src/settings.json

Current validated profile:

    preview.lores_max_height = 800
    preview.mjpeg_quality = 80

With the current 3936 x 2176 IMX283 mode this produces:

    1446 x 800
    approximately 33 FPS
    approximately 131 kB/JPEG for the test scene
    approximately 34.7 Mbit/s

This is intentionally lower than the maximum profile tested.

Rejected stress-test profiles:

- 1732 x 958, JPEG Q85: approximately 65.8 Mbit/s; too little real-time margin under simultaneous RAW + MJPEG load
- 1534 x 848, JPEG Q82: improved substantially but was not retained as the conservative production setting

Final reset-aware RAW stress validation for 1446 x 800 Q80:

- RAW: 3936 x 2176, 12-bit, approximately 33 FPS
- MJPEG client actively consuming the web stream
- 10 seconds measured after explicit per-take counter reset
- 331 RAW frame-stat samples
- frame rate mean: approximately 33.000 FPS
- droppedFrames remained exactly 0
- writeFailures remained exactly 0
- disk buffer depth peak: 3
- frames in flight peak: 5
- approximately 3.0 GiB MemAvailable after test
- temperature approximately 56 C
- get_throttled = 0x0

RAW recording reliability has priority over web-preview resolution/quality. Any future quality increase must pass the same simultaneous RAW + active-MJPEG stress test.

## Responsive / PWA local camera UI

The local IMX283/Pi 5 camera now uses a shared responsive web shell for Camera, Clips and Offload.

Current web-preview profile:

    1446 x 800
    JPEG quality 80
    approximately 33 fps

Camera controls adapt to desktop, portrait phone/tablet and compact landscape. Compact landscape uses retractable overlays so monitoring controls do not permanently consume the image area.

Fullscreen behavior is browser-capability aware. Desktop/compatible browsers use the Fullscreen API with explicit Enter/Exit controls. On iPhone/iPad the reliable browserless workflow is Add to Home Screen; the PWA manifest requests fullscreen/standalone display.

Clips now shows a REC indicator/timecode during recording and automatically reloads its clip list only after the take has fully finalized and all write/buffer flags have cleared.

The Clips page does not currently embed live camera preview.

See [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md) for implementation details and long stress-test results.

## Recording-state synchronization

The Camera and Clips web pages now share the same canonical REC state, is_recording.

The Camera page receives the state in its initial Socket.IO payload, receives start/stop pushes through recording_state, and also polls /recording-state once per second as a recovery mechanism.

This fixes the previous case where a take could be started while viewing Clips and the Camera page would fail to show recording state after navigation.

The old red page/border treatment was removed. Camera now uses a small blinking red REC dot with responsive placement:

- desktop: aligned to the right side of the actual displayed image
- portrait mobile/tablet: top-right of the image
- compact landscape: top-left, away from the retractable controls button

The HDMI GUI uses the same is_recording state for its own blinking REC dot.

### Clips REC timer format

The Clips recording badge displays elapsed duration as M:SS rather than HH:MM:SS:FF.

The source is recording_time, the floating-point elapsed-seconds value from /recording-state. The API still exposes the complete frame timecode for diagnostics, but frames are intentionally hidden from the Clips badge because they update too rapidly to be useful to an operator.

The state poll remains at 500 ms for responsive REC state changes; the displayed timer only changes once per elapsed second.

### Clips timer race protection and mobile control placement

The Clips REC timer now guards against the previous take duration remaining temporarily in recording_time when a new recording starts.

On an observed recording start edge, the badge shows 0:00 until the new take timer is detected near zero. After that, the visible M:SS counter is monotonic and cannot jump backwards during the same take. Opening Clips during an already-running take still shows the current elapsed duration.

Portrait Camera layout also now places LOOK/LUT selection in the top area immediately left of Clips. TAG occupies the former LUT position in the tool row and matches the other monitoring-tool buttons more closely.

The portrait REC dot is positioned from the actual image rectangle. Compact-landscape Clips is offset left of the retractable controls button to prevent overlap.

## Clips proxy progress and independent clip LUT

Clips proxy generation now runs in the background and reports progress inside the corresponding clip row instead of using a blocking player overlay.

The visible states are queued, rendering percentage, paused during recording, verifying, ready and error. When a clip finishes encoding, its row changes to proxy ready without interrupting whatever clip is currently playing.

The Clips player has a separate look selector. It stores per-clip choices under clipLuts and is intentionally isolated from the Camera live-preview LUT preference.

The live MJPEG Camera stream is rebuilt from window.location.hostname and port 8000, which prevents iPhone/PWA navigation from accidentally targeting localhost after returning from Clips.
