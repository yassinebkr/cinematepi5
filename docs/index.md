# Cinemate Docs

Welcome to the **Cinemate** project — an open-source boilerplate for building your own digital cinema camera using a Raspberry Pi 4 or 5. It combines a lightweight Python interface with the [CinePi‑raw recorder by Csaba Nagy](https://github.com/cinepi) for capturing 12‑bit CinemaDNG footage.

To begin, follow the steps in [Quick start](getting-started.md). Later sections cover customising your build. For more background, see the [Overview](readme.md).

For sharing your build with others, inspiration and discussion, make sure to join the [CinePi Discord](https://discord.gg/Hr4dfhuK).

## Raspberry Pi 5 camera stack

The Pi 5 build includes the current IMU calibration workflow, live LEVEL/SHAKE telemetry, HDMI preview tuning, I2C device support and power-validation notes. See [IMU calibration, HDMI preview and live HUD](imu-calibration-and-live-hud.md).

## Web preview and responsive controller

For the current responsive camera UI, PWA/fullscreen behavior, web-preview quality profile, Clips/Offload mobile layouts, Clips REC indicator/auto-refresh and long RAW+MJPEG validation, see [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md).

## 3D LUTs and IMX283 colour calibration

For the real WebGL2 .cube implementation, independent Camera/Clips look state,
GPU self-test, interpolation, CORS and troubleshooting, see
[Real 3D LUTs in CineMate](3d-luts.md).

For sensor-side colour work, including the current experimental IMX283 tuning,
existing dark-calibration result, ct_curve semantics, upstream Raspberry Pi
PiSP tuning and a calibration path that does not require an expensive colour
chart, see [IMX283 colour calibration](imx283-color-calibration.md).

