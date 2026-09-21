# Simple GUI Refresh Tuning

This page describes the current local Pi 5 HDMI GUI path.

The live camera image and the Python GUI are separate:

- cinepi-raw presents the lores camera stream through a DRM/KMS hardware plane.
- SimpleGUI draws overlays and status information through /dev/fb0.

Changing SimpleGUI FPS therefore changes HUD/UI responsiveness, not the camera sensor cadence.

## Current target

In src/module/simple_gui.py:

    self.target_fps = 30
    self.min_frame_interval = 1 / self.target_fps

The camera pipeline has been directly measured at approximately 33 FPS in the current IMX283 mode, so a 30 FPS GUI is a useful match without asking the framebuffer layer to outrun the camera.

## RGB565 fast path

The old framebuffer path converted a full 1920 x 1080 RGBA frame to RGB565 with NumPy. That conversion took approximately 51.4 ms per frame and imposed a conversion-only ceiling around 19 FPS.

The current framebuffer path uses OpenCV COLOR_RGBA2BGR565 and limits OpenCV to one worker thread.

The output was verified byte-for-byte against the old converter on known pixels and random images.

Measured conversion costs on this Pi 5:

- old NumPy conversion: approximately 51.4 ms
- isolated OpenCV conversion: approximately 2.7 ms
- complete Pillow to NumPy view to OpenCV RGB565 path: approximately 11.2 ms

The one-thread policy leaves the remaining CPU cores available for capture, encoding and disk workers.

The legacy NumPy converter remains available as fallback if OpenCV is unavailable.

## Framebuffer writes

Framebuffer writes are unbuffered. The current hot path may pass a memoryview from the OpenCV-backed array rather than allocating another Python bytes copy.

The framebuffer remains a full-frame software UI path, so unnecessary redraws should still be avoided.

## Slow values

self.slow_refresh_interval remains the control for expensive slow-changing statistics such as CPU load, temperature and storage information.

Keep those values off the hot 30 FPS path whenever possible.

## Calibration rendering

The full-screen IMU calibration view uses a software-rendered triangulated 3D sphere. It has a separate lower refresh cap so calibration visualization does not waste CPU needed for recording.

## Recording validation

The 30 FPS GUI was tested during 3936 x 2176 12-bit RAW capture at approximately 33 FPS.

Observed during the stress test:

- 0 camera-frame drops
- 0 write failures
- approximately 405 MiB/s sustained storage writes
- RAM-buffer peak 5 / 148 frames
- minimum MemAvailable approximately 2.93 GiB
- cinepi-raw RSS approximately 323 MiB peak
- SimpleGUI/Cinemate RSS approximately 115 MiB peak
- temperature approximately 54.5 C peak

See [IMU calibration, HDMI preview and live HUD](imu-calibration-and-live-hud.md) for the full validation record.

## Browser preview is independent

The browser MJPEG stream is separate from the Python framebuffer conversion path described above.

The current validated browser stream is 1446 x 800 JPEG Q80 at approximately 33 fps. A continuous browser/MJPEG consumer was present during successful 30-second and 40-second full-resolution RAW validation takes.

See [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md).
