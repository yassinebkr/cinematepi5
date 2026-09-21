# Web preview, responsive UI, PWA and Clips live state

Local development state for the IMX283 / Raspberry Pi 5 camera, validated on 2026-09-20.

These changes are local to the running camera and are not yet pushed to the public fork.

## Goals

This phase addressed four practical problems:

1. Web preview image quality was too low.
2. Camera controls were desktop-oriented and required manual zooming on phones/tablets.
3. Fullscreen behavior was inconsistent, especially on iPhone/iPad.
4. Clips and Offload were not comfortable in portrait orientation, and Clips did not show recording state or refresh after a completed take.

## Web preview signal path

The browser receives MJPEG directly from cinepi-raw on port 8000:

    http://<camera>:8000/stream

The CineMate control UI remains on port 5000:

    http://<camera>:5000

The Clips page does not currently embed the live MJPEG stream. It remains dedicated to playback of previously recorded clips.

### Current validated preview profile

The current local settings are:

    preview.lores_max_height = 800
    preview.mjpeg_quality = 80

For the current IMX283 RAW mode, this produces approximately:

    1446 x 800
    JPEG quality 80
    ~33 MJPEG frames/s

The stream is configured through:

    /home/pi/cinemate/src/settings.json
    /home/pi/post-processing0.json

cinepi_multi.py synchronizes the configured MJPEG quality into the active post-processing configuration at launch.

The earlier experiments with larger/higher-quality web profiles were not retained because long recording tests showed less storage/processing margin. The current 1446 x 800 / Q80 profile was selected as the practical validated point.

## Responsive camera page

Shared responsive styles are in:

    /home/pi/cinemate/src/module/app/static/css/cinemate-responsive.css

Shared browser/PWA/fullscreen behavior is in:

    /home/pi/cinemate/src/module/app/static/js/cinemate-app.js

The camera page now uses viewport-safe responsive layout rather than a fixed desktop geometry.

### Desktop

- live image uses the available preview area without reserving the old fixed 136 px blank margin
- camera tools overlay the image instead of permanently shrinking it
- fullscreen uses a real Enter / Exit state
- an Exit Fullscreen floating control remains accessible in fullscreen mode

### Phone/tablet portrait

- top camera parameters form a compact responsive grid
- the camera image uses its natural wide aspect near the top of the available area
- the remaining black space below the image is intentionally used for camera controls
- tool buttons wrap instead of being truncated
- bottom telemetry is arranged as a compact grid
- the controls can be hidden to give the image the whole viewport

### Phone/tablet landscape

- the live image owns the full viewport
- control bars are translucent overlays
- controls are collapsed by default on compact landscape displays
- the floating menu button toggles the control overlays
- scopes are hidden from the compact landscape overlay to preserve image area

The collapsible-control button is:

    #ui-toggle

## Fullscreen behavior

The old implementation used overlapping click/touch handlers and delayed attempts to enter fullscreen. That was unreliable because browsers require fullscreen requests to occur directly in a user activation event.

The new implementation uses one explicit click path and tracks the real fullscreen state.

On browsers that support the Fullscreen API, the control changes between:

    Enter Fullscreen
    Exit Fullscreen

A separate floating Exit Fullscreen control is shown while fullscreen is actually active.

### iPhone / iPad

Arbitrary page fullscreen is not consistently exposed by iOS WebKit, including browsers such as Safari and Brave which share the WebKit engine.

On iOS/iPadOS, the preferred camera workflow is therefore:

    Share
    -> Add to Home Screen
    -> launch CinePi from the Home Screen icon

That launches the camera controller in standalone/fullscreen web-app mode without browser chrome.

The UI no longer pretends that a normal browser tab can always enter fullscreen on iOS. If the API is unavailable, the user receives Home Screen installation guidance instead.

## PWA shell

The web application now includes:

    /static/manifest.webmanifest
    /static/sw.js
    /static/icons/cinepi-192.png
    /static/icons/cinepi-512.png
    /static/icons/apple-touch-icon.png

The manifest requests fullscreen/standalone display and allows either portrait or landscape orientation.

The service worker only caches static application-shell assets. It deliberately does not intercept:

- the live MJPEG stream
- frame.jpg
- dynamic API/state requests

This avoids stale camera state and avoids buffering the video stream through the service worker.

Important Android limitation:

A standards-compliant installable PWA normally requires a secure context (HTTPS) except localhost. The current camera control UI is intentionally still plain HTTP on the LAN. Android browser behavior around Add to Home Screen can therefore vary by browser/version. Local HTTPS can be added later if guaranteed Android PWA installation becomes a requirement.

## Clips responsive layout

The Clips page is now responsive in both orientations.

Desktop/landscape:

- playback area and clip list share the available width
- list remains independently scrollable

Portrait:

- playback is placed above the list
- thumbnails become wider and easier to inspect
- metadata/actions wrap below rather than overflowing horizontally
- header filters and actions wrap into usable rows

The Clips page currently shows playback proxies only; live camera preview was explicitly deferred for possible future work.

## Clips recording-state indicator

The Clips page now shows a visible REC indicator while the camera is recording.

UI element:

    #rec-indicator

It includes:

- animated red dot
- REC text
- current recording timecode

The page polls a lightweight local API every 500 ms:

    GET /clips/recording-state

This endpoint reads the existing in-process Redis controller cache; it does not spawn redis-cli and does not scan the SSD.

Returned state includes:

- recording
- writing
- writing_buf
- buffering
- finalized
- recording_time
- timecode
- framecount

## Automatic Clips refresh after a take

The Clips page tracks the transition:

    recording=true
    -> recording=false
    -> writers/buffers fully drained
    -> finalized=true

Only after the take is fully finalized does the browser reload the Clips page.

This is intentional. Reloading immediately when REC falls could expose an incomplete clip while buffered DNG frames are still being written.

The backend flow was validated with a real recording:

- REC active state observed successfully
- live timecode advanced
- recording stopped
- finalized became true only after writers/buffers cleared
- a new clip directory appeared
- the refreshed /clips render contained the new clip

Validation clip:

    CINEPI_26-09-20_032809_F17_C00001_cam1

## Offload responsive layout

Offload was updated together with Clips.

Portrait mode:

- destination and controls stay readable without browser zoom
- each clip row becomes a two-line grid
- name/size occupy the first line
- backup status occupies the second
- selection remains easy to use on touch screens

Landscape/desktop retains a denser layout.

## Long RAW + web-preview validation

After the user removed obsolete test recordings and freed SSD space, the final 1446 x 800 / Q80 profile was tested while a real MJPEG client continuously consumed the stream.

### 30-second test

RAW:

    3936 x 2176
    12-bit
    33 fps

Result:

- target: 30 s
- recorded duration: ~30.3 s
- 999 DNG frames
- DNG sequence drops: 0
- write failures: 0
- MJPEG: ~32.91 fps
- MJPEG bandwidth: ~36.9 Mbit/s
- max RAM buffer occupancy: 0 frames in sampled intervals
- max frames in flight: 2
- minimum MemAvailable: ~2690 MiB
- cinepi-raw RSS peak: ~361 MiB
- CPU temperature max: ~62.8 C
- NVMe temperature max: ~47.9 C
- EXT5V minimum: ~4.853 V
- get_throttled remained 0x0

Clip:

    CINEPI_26-09-20_032929_F26_C00002_cam1

### 40-second test

RAW:

    3936 x 2176
    12-bit
    33 fps

Result:

- target: 40 s
- recorded duration: ~40.4 s
- 1333 DNG frames
- DNG sequence drops: 0
- write failures: 0
- MJPEG: ~33.00 fps
- MJPEG bandwidth: ~36.4 Mbit/s
- max RAM buffer occupancy: 0 frames in sampled intervals
- max frames in flight: 2
- minimum MemAvailable: ~2694 MiB
- cinepi-raw RSS peak: ~360 MiB
- CPU temperature max: ~63.35 C
- NVMe temperature max: ~49.85 C
- EXT5V minimum: ~4.882 V
- get_throttled remained 0x0

Clip:

    CINEPI_26-09-20_033037_F24_C00003_cam1

The user's practical tolerance is up to approximately 5 dropped RAW frames per 30 s; both final validation runs recorded zero DNG sequence drops.

## Storage caveat discovered during long testing

Earlier long tests, before old test recordings were removed, exposed a storage-dependent failure mode:

- NVMe write rate initially held around 400 MB/s
- it later collapsed through approximately 285 MB/s, 80-90 MB/s, then single-digit MB/s
- the RAM recording pool filled
- cinepi-raw stopped recording with:

    RAM pool exhausted — recording stopped

The same behavior was reproduced without a web-preview client, proving that the web stream was not the root cause.

NVMe:

    Corsair MP600 MICRO 1 TB
    Phison PS5021-E21
    DRAM-less
    PCIe Gen3 x1 on the Pi 5 link

No thermal, power or kernel I/O error accompanied the failure.

After older test recordings were removed and the drive had more free space / idle recovery time, the final 30 s and 40 s tests above completed cleanly at full RAW rate.

Interpretation:

The failure is storage-state dependent and is consistent with transient sustained-write/cache/garbage-collection behavior rather than a deterministic web-preview bottleneck.

Do not claim unlimited-duration 3936 x 2176 12-bit 33 fps RAW operation solely from short tests. For production use, continue monitoring:

    write_speed_to_drive
    buffer / frames in flight
    MemAvailable
    NVMe temperature
    get_throttled

A direct long-duration fio benchmark can be performed later if storage characterization becomes a priority, but it has not been run as part of this phase.

## Current acceptance state

Validated:

- responsive camera UI on desktop, phone and tablet layouts
- portrait and landscape responsive Clips/Offload structure
- Home Screen standalone mode on iOS works as the reliable fullscreen path
- desktop Fullscreen API path has explicit enter/exit behavior
- web preview 1446 x 800 Q80 at approximately 33 fps
- simultaneous 30 s and 40 s full-resolution RAW recordings with continuous MJPEG consumer
- Clips REC indicator backend/state flow
- automatic post-finalization Clips refresh backend/state flow

Still worth physical/browser follow-up:

- verify the latest camera-page portrait command layout on representative phone/tablet sizes
- verify the retractable landscape tool overlay feels appropriately compact
- verify desktop fullscreen floating Exit control visually
- decide later whether Clips should optionally embed live camera preview
- decide later whether local HTTPS is worth adding for stricter Android PWA installation

## Canonical recording-state synchronization

Recording indication is now synchronized across HDMI, the main Camera web page and the Clips page from a single canonical state:

    Redis key: is_recording

The visual REC state no longer depends on:

- which web page triggered recording
- the HDMI framebuffer background colour
- is_writing / is_writing_buf
- navigation between Camera and Clips

The /recording-state endpoint is the shared lightweight HTTP state source. /clips/recording-state remains as a compatibility alias.

The main Camera page receives recording state in three ways:

1. recording is included in the Socket.IO initial_values payload, so opening Camera while a take is already running immediately shows REC.
2. recording_state Socket.IO events push subsequent start/stop changes.
3. A 1-second /recording-state poll acts as a recovery path after navigation, visibility changes or missed socket events.

Clips uses the same canonical state for its REC indicator and continues to wait for writer/buffer finalization before refreshing the clip list.

### HDMI recording indicator

The old full-frame / full-bar red recording treatment was removed.

During active recording the HDMI framebuffer now draws a small blinking red circle in the right-side HUD strip. This indicator is independent of the LEVEL HUD toggle and is driven only by is_recording.

is_writing and the buffer flags remain available for internal write/finalization behaviour but no longer define the user-facing REC state.

The existing blue preroll / transient-state background is intentionally separate from recording. Do not interpret the blue startup/preroll state as a REC indicator.

### Web recording indicator placement

The main Camera page uses a small blinking red circle rather than a red border or red top/bottom bars.

Placement is responsive:

- desktop / large landscape: positioned relative to the actual contain-fitted MJPEG image, preferably in the right-side unused gutter; if no gutter exists, it sits just inside the image edge
- phone/tablet portrait: overlaid at the top-right of the video so it consumes no horizontal layout width
- compact phone/tablet landscape: top-left, avoiding the retractable controls button at top-right

The indicator is recalculated on viewport/orientation changes.

### Synchronization validation

A real recording test validated the exact navigation race that previously failed:

- system idle: is_recording=0
- REC started through the normal control path
- /recording-state: recording=true
- /clips/recording-state: recording=true
- Redis is_recording=1
- a new Camera Socket.IO connection was then opened while REC was already active
- its initial_values.recording was immediately true
- its background state was black, not red
- the already-open web client received recording_state=false when the take stopped
- Redis and both HTTP endpoints returned recording=false after stop/finalization

The HDMI framebuffer was also sampled directly:

- idle: 0 red indicator pixels in the test region
- bright REC blink phase: 489 red pixels
- dark blink phase: 0 red pixels
- after STOP: 0 red pixels

This confirms that the HDMI dot follows the same canonical state and that the old full-red recording background is no longer active.

Note: earlier exploratory attempts were made too close to CineMate startup and coincided with the intentional blue preroll/transient background. The final validation above was run after CineMate had fully stabilized and is the authoritative result.

### Clips REC elapsed-time display

The Clips REC badge deliberately does not display the full SMPTE-style recording timecode.

The state API exposes both:

    recording_time   elapsed seconds as a floating-point value
    timecode         HH:MM:SS:FF

The final FF field is a frame counter. At approximately 30 fps and a 500 ms UI poll interval it can visibly jump by about 15 frames per update, which is technically correct but visually noisy for a simple recording-duration badge.

The Clips UI therefore formats recording_time as:

    M:SS

Examples:

    5.24 seconds  -> 0:05
    65.91 seconds -> 1:05

The recording-state endpoint is still polled every 500 ms so REC start/stop remains responsive, but the visible duration text is only changed when the integer elapsed second changes.

The complete timecode remains available through /recording-state for diagnostics and synchronization.

### Clips timer stale-value race protection

A race was found when starting a new take while the Clips page was already open.

recording_time intentionally retains the previous take duration until the new take timer is reset on the first real recorded frame. That means the state can briefly look like:

    is_recording = 1
    recording_time = previous take duration

For example, a previous 6-second take could briefly expose 6.x seconds at the start of the next take.

The Clips UI now uses a per-take monotonic latch:

- a false -> true recording edge always displays 0:00 immediately
- stale recording_time from the previous take is ignored
- the UI waits until it observes the new timer reset/decrease near zero
- once the new timer is accepted, displayed elapsed time may only move forward for that take
- opening Clips in the middle of an already-running take still uses the current elapsed duration immediately

The implementation deliberately does not modify recording_time, HH:MM:SS:FF timecode, Gyroflow data or metadata.

Validation used two consecutive real takes. The second take began while Redis still contained approximately 4.56 seconds from the previous take. The displayed sequence remained monotonic:

    0:00 -> 0:01 -> 0:02 -> 0:03 -> 0:04

No stale duration was shown and no backward reset occurred.

### Mobile camera-control placement refinement

Portrait phone/tablet layout now moves the real LUT selector into the top parameter area, directly to the left of the Clips button.

The TAG control moves into the exposure/tool-button row and uses the same general size as HIST, WAVE, VECT, ZEBRA, PEAK and LEVEL rather than occupying a large full-width block.

The DOM nodes themselves are moved rather than duplicated, so existing event listeners and LUT/TAG state remain intact across orientation changes.

The Web REC dot in portrait is positioned against the actual displayed MJPEG image rectangle rather than the stream container origin. This keeps the dot inside the camera preview even though the tool controls are placed above the image in portrait.

In compact landscape, Clips is explicitly offset to the left of the retractable controls close button so the two controls cannot overlap.

## Clips background proxy progress

Proxy generation is now non-blocking from the Clips page.

Clicking a clip without a proxy:

- queues proxy generation in the background
- leaves the currently-playing clip untouched
- does not pause or replace the player
- shows progress directly inside the corresponding clip row/card
- removes the progress bar once the proxy becomes ready

No full-player progress overlay is used.

The row can show states such as:

    queued
    rendering 42%
    paused 42%
    verifying
    proxy ready

The progress bar is driven by the Clips status endpoint for the selected clip.

The proxy generator exposes:

- state
- current frame
- total frames
- percentage
- queue position
- pause state
- ready state

A real background render test was run on:

    CINEPI_26-07-26_104437_F25_C00003_cam1

with 10 DNG frames. Observed states were:

    queued
    encoding 0%
    encoding 10%
    verifying 100%
    ready 100%

The proxy completed successfully. The browser UI does not take over the player when the render completes.

A later test intentionally landed behind another queued render and reported queue_position=2. This confirms that the UI/API also exposes queue order instead of pretending every render begins immediately.

The proxy daemon runs as:

    proxy-gen.service

and is active together with CineMate and gyrologd.

## Independent LUT control for Clips

The Clips player now has its own discreet LUT/look selector integrated into the player area.

It is intentionally independent from the Camera live-preview LUT selector.

Camera state:

    localStorage key: lut

Clips state:

    localStorage key: clipLuts

The Clips selector applies only to the currently selected clip player. It does not:

- change the live Camera preview LUT
- modify RAW files
- modify the generated proxy MP4
- alter metadata

The chosen Clips look is stored per clip name so different clips can retain different preview looks.

Static validation confirms that clips.html has no reference to the Camera lut preference and only uses clipLuts.

## MJPEG recovery after Clips / PWA navigation

A regression was found where an old stream URL could point to localhost from the client point of view. On an iPhone or PWA, 127.0.0.1 refers to the phone, not the Raspberry Pi.

The live stream URL is now reconstructed in browser JavaScript using:

    window.location.hostname
    data-stream-port=8000

Conceptually:

    http://current-browser-host:8000/stream

The Camera page also reconnects the stream on:

- pageshow / back-forward navigation
- return to online state
- return to visible state

Safari/WebKit error events do not directly trigger a restart loop because multipart MJPEG can emit transient error events even while the stream remains useful.

A local stream probe after the fix decoded 30 JPEG frames successfully.

## Camera mobile layout follow-up

Portrait:

- the preview now uses the remaining vertical space more deliberately instead of sitting immediately below the upper controls with a large unused black gap
- the image is centered in the available region
- LOOK/LUT remains in the upper controls area
- TAG remains sized like the other monitoring tools
- the REC dot is positioned from the actual rendered image rectangle rather than from the container origin

Compact landscape:

- scopes are no longer forcibly hidden
- HIST / WAVE / VECT output is rendered as a compact overlay when its tool is active
- the Clips button is offset away from the retractable close/menu control
- the REC dot is anchored inside the viewport rather than to an unstable edge location

These changes are responsive-layout behavior only; they do not change the RAW recording pipeline.

Current shared asset revision:

    20260920l

Current service-worker shell revision:

    v12
