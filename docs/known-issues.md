# Known issues

This page includes local IMX283 / Pi 5 issues that are not necessarily upstream Cinemate issues.

## Physical encoder buttons

The direct-GPIO rotary encoder push buttons are not currently reliable on this camera. The calibration workflow therefore must remain fully operable from the web UI.

Current local pins:

| Control | CLK | DT | Button |
| --- | ---: | ---: | ---: |
| Shutter | GPIO 23 | GPIO 24 | GPIO 25 |
| White balance | GPIO 6 | GPIO 13 | GPIO 5 |
| ISO | GPIO 17 | GPIO 27 | GPIO 4 |

The ISO rotary encoder itself is also currently not working despite repeated wiring checks.

Do not make calibration depend exclusively on a hardware click until these inputs are diagnosed.

## Calibration coverage duration

The current finite-area spherical coverage model is much faster than the old one-point-per-cell method and has been physically validated, but the user still considers the coverage stage slightly longer than ideal.

Future tuning should shorten this stage without weakening the accelerometer fit requirements.

## Calibration gravity-vector readability

The 3D coverage sphere is now genuinely triangulated and rotating, but the live gravity/vector cue could be made easier to interpret at a glance.

## Monitor auto-rotation / double black flash

No Pi-side display rotation path was found. cinepi-raw runs with rotation 0.

If the HDMI monitor blanks twice and flips 180 degrees when physically inverted, check the monitor OSD for an automatic mirror/rotation feature. Do not add compensating Pi rotation unless the monitor-side behavior has first been disabled.

## Historical undervoltage flag

An old boot reported throttled=0x50000. After reboot, official 27 W PSU negotiation was confirmed at 5 V / 5 A and full RAW recording with the USB-powered monitor attached remained throttled=0x0.

The historical event was not reproduced. If it returns, inspect vcgencmd pmic_read_adc and test the monitor from an independent power source before changing Pi firmware settings.

See [IMU calibration, HDMI preview and live HUD](imu-calibration-and-live-hud.md).

## Android installed PWA requires HTTPS

The responsive/PWA shell is present, but the camera is currently served over plain HTTP on the LAN.

iOS/iPadOS Home Screen mode can use the Apple web-app metadata, but a guaranteed installable standalone PWA on Android/Chromium-family browsers requires a trusted HTTPS secure context.

A future HTTPS implementation should reverse-proxy both the CineMate UI/Socket.IO service and MJPEG stream under the same secure origin. Do not enable HTTPS only on port 5000 while leaving the embedded preview on plain HTTP port 8000, because browsers may block it as mixed content.

## Storage-state dependent sustained RAW writes

Long testing exposed a storage-state-dependent failure mode on the Corsair MP600 MICRO 1 TB: sustained write speed can fall well below the approximately 400 MB/s required by 3936 x 2176 12-bit 33 fps RAW, allowing the RAM pool to fill until recording stops.

This failure reproduced without a web-preview client and is therefore not attributed to MJPEG.

After older test recordings were removed and the SSD had more free space / recovery time, final 30-second and 40-second RAW + MJPEG tests completed with zero DNG sequence drops and zero write failures.

Treat sustained recording duration as dependent on SSD state until the NVMe has been characterized more deeply.

## iOS browser fullscreen

iPhone/iPad browsers may not expose arbitrary page Fullscreen API behavior even when desktop browsers do. Use Add to Home Screen and launch CinePi as a standalone web app for the reliable full-screen camera controller.

## Clips live preview

The Clips page intentionally does not show the live camera MJPEG feed at this stage. It now shows recording state and refreshes automatically after finalization; embedding live preview there is deferred for future UX work.

## Recording-state visual semantics

REC indication now comes exclusively from is_recording.

The blue framebuffer state seen during preroll/startup is a separate transient state and should not be interpreted as active recording. is_writing and buffer-flush states are also separate from the user-facing REC indicator.

If REC appears inconsistent after a future change, compare:

    redis-cli get is_recording
    GET /recording-state
    Socket.IO initial_values.recording
    Socket.IO recording_state

All four should agree.

## Legacy REC edge versus recording_time

recording_time is intentionally aligned to the first real recorded frame, while is_recording represents the persistent take state. Therefore recording_time can retain the previous take value for a short interval after a new is_recording rising edge.

The Clips UI handles this with a per-take latch and should not expose the stale duration.

Do not move the camera recording timer earlier merely to make the UI start at zero; doing so would weaken frame/timecode alignment. The UI should continue to handle the transient state instead.

## Clips proxy generation semantics

Proxy creation is asynchronous and can pause while recording is active. The Clips page reflects this in each clip row rather than blocking playback.

A proxy-ready state means the MP4 proxy has been fully generated and verified. RAW DNG files remain the source material.

Multiple proxy requests can queue. The status API exposes queue position so the UI can show that a render is waiting rather than stalled.

## Browser-host MJPEG semantics

The live MJPEG endpoint must always use the host from which the user opened CineMate. Never hard-code 127.0.0.1 into browser-visible stream URLs; localhost in Safari, Brave or Chrome on a phone refers to the phone itself.

The browser now derives the host dynamically.

## Clips LUT semantics

Clips looks are browser-side preview transformations only and are stored separately from the live Camera LUT. They do not bake a LUT into the proxy or RAW material.
