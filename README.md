# CineMate

## Fork status

This repository is a downstream fork of [Tiramisioux/cinemate](https://github.com/Tiramisioux/cinemate). It retains CineMate as its foundation, but this fork has substantially diverged in reliability hardening, recovery and configuration tooling, monitoring UX, IMU workflow, IMX283 integration, installation architecture, and regression coverage.

Treat the code, documentation, installation procedures, and compatibility claims in this repository as specific to this fork unless explicitly stated otherwise. Upstream work is still reviewed and credited where relevant, but changes here should not be assumed to be upstream-supported or directly suitable for upstream.

CineMate is an open-source camera-control and monitoring stack for building digital cinema cameras around CinePi RAW.

The project combines 12-bit CinemaDNG recording, a responsive browser controller, HDMI monitoring, physical controls, storage management, IMU telemetry and post-production helpers in one camera-oriented runtime.

## Current focus

This fork is currently being hardened around the Sony IMX283 while retaining CineMate's broader sensor database and control architecture.

The current development priorities are reliability, deterministic configuration, colour-management clarity, useful field monitoring, reproducible installation and regression coverage.

## Main capabilities

- 12-bit CinemaDNG recording through CinePi RAW
- browser-based Camera and Clips interfaces
- responsive phone, tablet and desktop layouts
- real WebGL2 3D .cube LUT monitoring
- first-party CinePi Rec.709 LUT pack
- Histogram, Waveform and Vectorscope
- adjustable Zebra exposure warnings
- adaptive focus Peaking
- roll, pitch and shake monitoring from the IMU
- per-take 1 kHz Gyroflow-compatible gyro/accelerometer logs
- HDMI Simple GUI
- GPIO buttons, rotary encoders, analog controls and I2C devices
- SSD monitoring, automount and recording safeguards
- Redis-backed camera state and control
- dynamic resolution profiles
- camera-specific libcamera tuning-file support with validation and safe fallback

## Recorded image and monitoring path

CinemaDNG remains the camera negative. Creative LUTs are display transforms and do not alter the recorded RAW frames.

The monitoring path is intentionally separated from the RAW path:

    IMX283 RAW
        -> libcamera PiSP development
        -> Rec.709 monitoring signal
        -> optional CinePi creative LUT
        -> browser or HDMI display

This separation lets the same CinePi creative .cube files be used in post-production without baking the look into the CinemaDNG sequence.

See [Rec.709 and post-production workflow](docs/rec709-post-workflow.md) and [Real 3D LUTs in CineMate](docs/3d-luts.md).

## Monitoring tools

The web controller includes field-oriented monitoring rather than decorative overlays.

- **Histogram** shows luma and individual RGB channel distributions.
- **Waveform** preserves horizontal image position and shows IRE guides.
- **Vectorscope** shows hue and saturation direction.
- **Zebra** supports 70, 80, 85, 90, 95 and 100 IRE thresholds.
- **Peaking** uses denoised Sobel gradients and an adaptive noise threshold.
- **Level** displays roll and pitch from the calibrated IMU.
- **ETTR** estimates remaining highlight headroom from the brightest RGB channel.

The [Monitoring tools operator guide](docs/monitoring-tools-user-guide.md) uses real CineMate screenshots and explains how to read each tool.

## IMU and stabilization

The ICM-42688 is used for both live camera orientation and post-production motion data.

Recorded takes can include a Gyroflow-compatible **gyro.gcsv** file containing 1 kHz gyro and accelerometer samples. The current implementation is suitable for Gyroflow workflows; tighter first-frame timestamp synchronization remains an area for further hardening.

See [IMU calibration, HDMI preview and live HUD](docs/imu-calibration-and-live-hud.md).

## Installation

The repository includes an installation script for the Pi 5 camera stack:

    git clone https://github.com/yassinebkr/cinematepi5.git
    cd cinematepi5
    sudo ./cinemate-install.sh

The installer builds and configures the CineMate dependencies, CinePi RAW/libcamera stack and system services. Review [Installation and building from source](docs/installation-steps.md) before installing on a camera that already contains irreplaceable configuration or footage.

For development work, use a dedicated branch and keep a tested rollback image of the camera SD card.

## Running and services

The main runtime is managed by **cinemate-autostart.service**.

Useful service commands:

    sudo systemctl status cinemate-autostart
    sudo systemctl restart cinemate-autostart
    journalctl -u cinemate-autostart -f

CineMate also includes support services for storage automount, Wi-Fi hotspot management and Redis log maintenance.

See [System services](docs/system-services.md) and [Troubleshooting](docs/troubleshooting.md).

## Configuration

Camera and hardware behaviour is configured through the CineMate settings structure. The current Pi 5 configuration includes per-camera geometry, display routing, tuning-file overrides, dynamic-resolution profiles, physical controls and storage policies.

See [Custom settings](docs/settings-json.md) and [Hardware controls](docs/hardware-controls.md).

## Colour pipeline

The current IMX283 build uses the full PiSP tuning from the camera's matching libcamera checkout rather than the earlier compact experimental tuning.

The colour pipeline is intentionally split into two jobs:

1. sensor/ISP calibration: black level, white balance, CCM, lens shading and tone mapping
2. creative monitoring: optional Rec.709 3D LUTs

Creative LUTs should not be used to hide sensor calibration errors.

See [IMX283 colour calibration](docs/imx283-color-calibration.md).

## LUT distribution

The shipping LUT directory contains first-party CinePi looks generated deterministically by **tools/generate_cinepi_luts.py**.

- CinePi Rec.709 Reference
- CinePi Natural
- CinePi Filmic Neutral
- CinePi Cinema Warm
- CinePi Soft Portrait

The manifest stores SHA-256 hashes so the pack can be reproduced and verified. Third-party development LUTs are intentionally excluded from the shipping set.

## Tests

Regression tests cover configuration migration, dynamic resolution, sensor parsing, storage behaviour, preview geometry, camera-control logic, tuning-file safety, LUT API behaviour, monitoring UI invariants and deterministic LUT generation.

Run the standard-library suites with:

    PYTHONPATH=src python3 -m unittest discover -v _test

Tests that exercise the full camera environment should be run inside the CineMate virtual environment on a Raspberry Pi 5.

## Documentation

Start with the [documentation home](docs/index.md). Useful entry points include:

- [Quick start](docs/getting-started.md)
- [Web GUI](docs/web-gui.md)
- [Monitoring tools operator guide](docs/monitoring-tools-user-guide.md)
- [Rec.709 and post-production workflow](docs/rec709-post-workflow.md)
- [IMX283 colour calibration](docs/imx283-color-calibration.md)
- [System services](docs/system-services.md)
- [Troubleshooting](docs/troubleshooting.md)

The MkDocs site configuration is in **mkdocs.yml**.

## Project lineage

CineMate originates from the work by Tiramisioux and the wider CinePi project. This Pi 5 fork preserves that foundation while integrating local Pi 5, IMX283, web-monitoring, colour-pipeline and reliability work.

See [Acknowledgements](docs/acknowledgments.md) for project credits and related repositories.

## Development status

The Pi 5 hardening work is intentionally developed on a review branch before being merged to main. Camera-facing UI changes should be tested on the actual camera, phone and desktop controller before release.

Before relying on the system for an important shoot, verify recording, storage throughput, preview, IMU logging and clip playback with the exact camera hardware and media that will be used.
