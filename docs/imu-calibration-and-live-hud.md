# IMU calibration, HDMI preview and live HUD

Local development state for the IMX283 / Raspberry Pi 5 camera build, validated on 2026-09-20.

This page documents the local work currently present on the camera. These changes are not yet pushed to the public fork and should not be confused with upstream Cinemate behavior.

## Current architecture

The camera display uses two independent layers:

- cinepi-raw is C++ and owns the live camera preview through a DRM/KMS hardware plane.
- Cinemate SimpleGUI is Python and draws the camera UI and HUD to /dev/fb0 using Pillow.
- The browser control UI is Flask + Socket.IO on HTTP port 5000.
- The clean browser preview stream is served separately on port 8000.

The live camera process currently runs the IMX283 at 3936 x 2176, 12-bit RAW, with a 1302 x 720 lores preview stream.

A full-screen maintenance UI such as IMU calibration must own the framebuffer. While imu_cal_active is 1, CinePiManager enforces preview off centrally and launches cinepi-raw with --nopreview. This invariant also survives a Cinemate process restart.

## IMU hardware and service

The IMU is an ICM-42688 at address 0x69. gyrologd runs as:

    /home/pi/.cinemate-env/bin/python3 /home/pi/gyrologd/gyrologd.py

Systemd unit:

    gyrologd.service

The sensor is configured for:

- gyro: +/-1000 deg/s at 1 kHz
- accelerometer: +/-4 g at 1 kHz
- FIFO accel + gyro packets
- raw Gyroflow sidecar logging for each clip

The calibration engine lives in:

    /home/pi/gyrologd/imu_calibration.py

Persistent files:

    /home/pi/gyrologd/imu_calibration.json
    /home/pi/gyrologd/level_zero.json
    /home/pi/gyrologd/level_cal.json

imu_calibration.json contains the physical sensor calibration. level_zero.json is the operator horizon zero. The legacy level_cal.json remains for compatibility with an uncalibrated camera.

Physical calibration and shooting horizon zero are deliberately separate.

## Guided IMU calibration

Calibration is started from the web UI:

    http://cinepi.local:5000

or by IP:

    http://192.168.1.94:5000

The server is plain HTTP, not HTTPS.

Open the LEVEL panel and press IMU CALIBRATION. The HDMI preview plane is disabled and a full-screen calibration UI takes over.

The calibration sequence is:

1. Gyroscope zero-rate bias.
   Keep the camera completely still for approximately 8 seconds. Motion resets the stable acquisition.

2. Accelerometer orientation coverage.
   Slowly tumble the camera through roll and pitch so gravity is observed from many sensor directions. Coverage uses a 3D spherical map. A finite 22 degree geodesic brush is used per accepted gravity direction; this is intentionally different from the older one-point-per-cell logic that made coverage unreasonably slow.

3. Accelerometer ellipsoid fit.
   Coverage and fit samples are separate. Normal hand motion can contribute to coverage, while only cleaner quasi-static observations are retained for the fit.

4. Six-face camera-frame alignment.
   The guided poses are normal, upside down, right side down, left side down, lens down and lens up.

5. Validation and save.
   The result screen reports gyro noise, accelerometer norm error, camera-frame alignment error and orientation coverage. Calibration is written atomically only after save.

Camera body convention after alignment:

    +X = forward through lens
    +Y = camera right
    +Z = down

The current calibration was physically validated and saved successfully.

Validation values from the saved calibration:

- orientation coverage: 94.8 percent
- gyro noise RMS: approximately 0.040 deg/s
- accelerometer RMS gravity error after correction: approximately 0.0267 g
- maximum six-face alignment error: approximately 4.65 degrees
- overall grade: good

## Calibration UI

The calibration sphere is now a real software-rendered 3D mesh rather than a flat circle with projected dots.

The renderer:

- builds a triangulated unit sphere
- rotates vertices in 3D
- back-face culls rear geometry
- performs perspective projection
- shades facets using a light vector
- paints covered regions directly onto the mesh
- slowly auto-rotates to make depth unambiguous
- marks the current gravity vector and a target uncovered region

The final visual design is intentionally restrained: black instrument background, minimal typography, thin separators and limited accent colors.

Known UI follow-up:

- make the current gravity/vector direction more immediately readable
- reduce the remaining time needed for the coverage phase slightly without reducing fit quality

## Physical controls

Local direct-GPIO rotary configuration:

| Control | CLK | DT | Push button |
| --- | ---: | ---: | ---: |
| Shutter | GPIO 23 | GPIO 24 | GPIO 25 |
| White balance | GPIO 6 | GPIO 13 | GPIO 5 |
| ISO | GPIO 17 | GPIO 27 | GPIO 4 |

Current hardware state:

- shutter and white-balance rotary movement are usable
- the physical click buttons are not currently reliable
- the ISO rotary encoder is not currently working despite wiring checks
- calibration can therefore be completed entirely from the web UI

The WB hold path still exists in code, but calibration must not depend on it until the button issue is fixed.

## HDMI preview optimization

The camera preview itself was already receiving one lores frame for each completed camera request. Direct cp_stats timing measured a stable 32.999 to 33.000 FPS with zero camera-frame drops.

The expensive path was the Python framebuffer HUD.

Before optimization:

- SimpleGUI cap: 12 FPS
- full-frame 1920 x 1080 RGBA to RGB565 conversion used NumPy
- conversion cost: approximately 51.4 ms per frame
- conversion-only ceiling: approximately 19.4 FPS
- framebuffer code reopened /dev/fb0 for every frame

Current implementation:

- SimpleGUI target: 30 FPS
- RGB565 conversion uses OpenCV COLOR_RGBA2BGR565
- OpenCV is limited to one worker thread to preserve camera CPU headroom
- output was verified byte-for-byte against the legacy NumPy converter on diagnostic and random-pixel frames
- end-to-end Pillow to NumPy view to OpenCV RGB565 conversion: approximately 11.2 ms per 1920 x 1080 frame
- direct OpenCV conversion itself: approximately 2.7 ms in the isolated benchmark
- framebuffer write is unbuffered
- the old NumPy converter remains as fallback

Files:

    /home/pi/cinemate/src/module/framebuffer.py
    /home/pi/cinemate/src/module/simple_gui.py

## RAW recording stress validation

The optimized preview/HUD path was validated while recording a workload harder than the 30 FPS requirement:

- 3936 x 2176
- 12-bit RAW
- approximately 33 FPS
- HDMI preview active
- 30 FPS Python GUI active
- calibrated IMU service active
- USB-powered HDMI monitor attached

A 12-second preview stress test measured:

- approximately 405 MiB/s sustained writes
- 0 dropped camera frames
- 0 write failures
- RAM buffer peak: 5 frames out of 148
- minimum MemAvailable: approximately 2.93 GiB
- cinepi-raw RSS peak: approximately 323 MiB
- GUI RSS peak: approximately 115 MiB
- maximum temperature: approximately 54.5 C

The test take was intentionally left on the SSD.

A later power stress take is:

    /media/RAW/CINEPI_26-09-20_022715_F27_C00001_cam1

It contains:

- 269 DNG frames
- approximately 3.3 GiB of media
- 8382 gyro data rows
- proxy and thumbnail sidecars

## Phase B: low-latency LEVEL and SHAKE

The old live HUD mixed intentional angular motion and shake. Phase B separates them.

LEVEL signal chain:

    ICM-42688 accel at 1 kHz
      -> bias and 3x3 accelerometer correction
      -> IMU-to-camera rotation
      -> short batch mean
      -> approximately 25 ms low-pass
      -> roll and pitch
      -> operator horizon zero

SHAKE signal chain:

    ICM-42688 gyro at 1 kHz
      -> calibrated gyro bias removal
      -> IMU-to-camera rotation
      -> 1.5 Hz low-pass trend = intentional camera motion
      -> high-frequency residual
      -> 60 ms RMS-like envelope
      -> calibrated gyro-noise-floor compensation

Redis publishes:

- imu_roll
- imu_pitch
- imu_shake
- imu_motion
- imu_seq
- imu_filter = phaseB-v1

Stationary Phase B measurements after calibration are typically:

- SHAKE: approximately 0.00 to 0.04 deg/s
- motion: approximately 0.00 to 0.02 deg/s

Physical testing confirmed that the new indicator feels substantially more immediate and useful than the previous implementation.

### HDMI near-zero display stabilization

The HDMI LEVEL renderer intentionally keeps the IMU signal chain untouched and stabilizes only the final presentation around level. At the current one-decimal HDMI readout precision:

- |roll| < 0.05° is displayed as unsigned 0.0°;
- the circle's horizon line uses the same snapped display value and is therefore exactly horizontal inside that range;
- roll at and beyond the display threshold is not suppressed and immediately regains its +/- sign and normal tilt;
- SHAKE remains independent and continues to render from imu_shake.

This addresses two manifestations of the same sub-pixel jitter: sign flicker around zero and apparent horizon-line thickness changes as an almost-horizontal 3-pixel line moves between framebuffer rows. The snap is display-only; imu_roll, imu_pitch, calibration state, raw Gyroflow logging and Phase-B filtering are not altered.

Regression coverage exercises the actual renderer path, including positive/negative sub-threshold roll, just-outside-threshold roll, large signed roll, non-zero SHAKE while LEVEL is snapped, and saturated SHAKE.

## I2C bandwidth fix

The original Pi 5 RP1 I2C1 bus was running at 100 kHz.

The ICM-42688 generates roughly 16 bytes per FIFO sample at 1 kHz. The raw FIFO payload alone therefore exceeds the practical bandwidth of 100 kHz I2C once addressing, ACK and transaction overhead are included.

Symptoms at 100 kHz:

- gyrologd blocked in kernel state i2c_dw_xfer
- approximately 200 ms service cycles
- live IMU publish rate only approximately 5 Hz

The boot configuration now contains under the all section:

    dtparam=i2c_arm_baudrate=400000

After reboot the live device-tree value was verified at:

    /proc/device-tree/axi/pcie@1000120000/rp1/i2c@74000/clock-frequency

and reads:

    400000

Measured Phase B publish rate after the change:

- approximately 30.5 Hz
- median update interval approximately 35.7 ms
- 95th-percentile update interval approximately 41.4 ms

The target was originally 50 Hz, but 30 Hz already matches the HDMI HUD cadence and is a better conservative operating point than moving immediately to unofficial 1 MHz I2C.

## Power investigation

Before the I2C reboot, vcgencmd reported:

    throttled=0x50000

This is a sticky historical state indicating that undervoltage and throttling had occurred sometime during that old boot. Neither condition was active at the time it was first inspected.

The camera uses the official Raspberry Pi 27 W USB-C supply. Firmware power data confirmed these advertised fixed PDOs:

- 5 V at 5.0 A
- 9 V at 3.0 A
- 12 V at 2.25 A
- 15 V at 1.8 A

The Pi reports:

- max_current = 5000 mA
- usb_max_current_enable = 1
- usb_over_current_detected = 0
- power_reset = 0

The HDMI monitor is powered from a Pi USB port and does not enumerate as a USB data device, consistent with a power-only USB connection.

After a clean reboot with the monitor still attached:

    get_throttled = 0x0

PMIC EXT5V measurements:

Idle:

- minimum approximately 4.888 V
- mean approximately 4.935 V
- maximum approximately 4.974 V

During full-resolution 12-bit RAW recording:

- minimum approximately 4.882 V
- mean approximately 4.913 V
- maximum approximately 4.953 V
- no sample below 4.85 V
- get_throttled remained 0x0 for every sample
- final sticky get_throttled remained 0x0
- no USB over-current was recorded

Conclusion: there is no reproducible present power fault. The previous 0x50000 was a historical transient from the previous boot. The exact original event cannot be timestamped from the sticky flag alone.

Do not change the power configuration based only on that historical flag. If undervoltage returns, compare behavior with the HDMI monitor powered independently and inspect PMIC EXT5V again.

Useful commands:

    vcgencmd get_throttled
    vcgencmd pmic_read_adc
    vcgencmd measure_temp

## Monitor auto-rotation

No Cinemate or Pi-side display-rotation code was found responsible for the monitor turning 180 degrees when the camera is inverted. cinepi-raw is launched with rotation 0.

The observed double-black flash followed by a 180-degree flip is consistent with monitor-side automatic image flipping. On FEELWORLD monitors this may be called Auto Mirror or a similar setting. If it recurs, disable automatic monitor rotation in the monitor OSD rather than adding a compensating Pi-side rotation.

## Web calibration and HTTP

The web UI is:

    http://cinepi.local:5000

or the Pi IP on port 5000.

Do not use HTTPS. The server does not provide TLS; attempting https:// on port 5000 produces browser errors such as SSL_ERROR_RX_RECORD_TOO_LONG and appears in the Flask log as malformed HTTP input.

The LEVEL panel includes:

- web level toggle
- HDMI level toggle
- ETTR advisor
- set zero
- IMU CALIBRATION
- CONTINUE while the wizard is active
- CANCEL while the wizard is active

## Important rollback snapshots

The local camera has been backed up before each major modification.

Important snapshots include:

    /home/pi/backups-before-imu-calibration/20260920-005627
    /home/pi/backups-before-web-cal-button/20260920-011547
    /home/pi/backups-before-imu-3d-sphere/20260920-012108
    /home/pi/backups-before-calibration-initial-preview-fix/20260920-012514
    /home/pi/backups-before-central-preview-invariant/20260920-012558
    /home/pi/backups-before-patchA-redesign/20260920-015632
    /home/pi/backups-before-preview-fps-optimization/20260920-021431
    /home/pi/backups-before-phaseB-imu-latency/20260920-022007
    /home/pi/backups-before-i2c400k/20260920-022516
    /home/pi/backups-before-documentation-update/20260920-023226

The first IMU backup contains full Git bundles for both Cinemate and gyrologd plus working-tree state.

## Source-control state

These changes are intentionally local at the time of writing.

Cinemate:

- repository: /home/pi/cinemate
- branch: dev
- local branch was already substantially ahead of upstream before this work
- current IMU/preview changes are uncommitted

gyrologd:

- repository: /home/pi/gyrologd
- branch: master
- calibration and Phase B changes are local and uncommitted

cinepi-raw:

- repository: /home/pi/cinepi-raw
- branch: dev
- the C++ recorder/DRM preview source was inspected but not modified during this calibration/preview work

Do not assume the public fork contains the running camera state.

## Next work

The next planned phase is web-preview/UI work.

Keep these future improvements in scope:

- make the calibration gravity/vector cue clearer
- slightly shorten orientation coverage while preserving fit quality
- diagnose all physical encoder push buttons
- diagnose the ISO rotary encoder
- preserve the calibration-preview invariant whenever new camera restart paths are added
- continue checking power sticky flags after long real-world sessions

## Web UI responsive/PWA and preview-quality phase

After Phase B, the browser UI was reworked for desktop, tablet and phone use.

Live, Clips and Offload now share a responsive stylesheet and common fullscreen/PWA JavaScript. Portrait and landscape are treated as first-class layouts rather than scaling a fixed desktop page.

The web MJPEG encoder is configurable. The current validated profile is 1446 x 800 at JPEG quality 80 and approximately 33 FPS. Higher 1732 x 958 / Q85 and 1534 x 848 / Q82 profiles were rejected because they left less real-time margin during simultaneous 3936 x 2176 12-bit RAW stress testing.

The final Q80 / 1446 x 800 profile passed a reset-aware 10-second stress test with zero camera drops and zero write failures while an MJPEG client remained connected.

The PWA shell and iOS Home Screen metadata are present. Android true-PWA installation still needs a trusted HTTPS reverse-proxy layer because the current camera UI and stream are served over plain HTTP.

## Web-preview phase update

The subsequent web-preview phase is now implemented locally. The live camera page, Clips page and Offload page share a responsive/PWA shell, and the production web-preview profile is currently 1446 x 800 JPEG Q80 at approximately 33 FPS.

A reset-aware simultaneous RAW + active-MJPEG stress test confirmed droppedFrames=0 and writeFailures=0 for the retained profile.

See web-gui.md for responsive behavior, PWA/fullscreen behavior and preview-quality benchmark details.

## Web preview phase validation

The subsequent web-UI phase retained the 30 FPS HDMI HUD and added a responsive/PWA browser controller.

The final validated browser-preview profile is:

    1446 x 800
    JPEG Q80
    approximately 33 fps

With a continuous MJPEG client connected, 3936 x 2176 12-bit RAW at 33 fps completed both 30-second and 40-second validation takes with zero DNG sequence drops and zero write failures after obsolete test recordings were removed from the SSD.

See [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md) for the complete browser and storage validation record.
