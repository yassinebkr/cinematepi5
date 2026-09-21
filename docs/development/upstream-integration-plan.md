# Upstream integration plan

This document tracks selective integration from the current upstream CineMate repository:

    https://github.com/Tiramisioux/cinemate

The Pi 5 branch has substantial independent work, so upstream is integrated feature by feature rather than through a bulk merge or rebase.

## Repository relationship

At the beginning of the hardening pass:

- local target repository: **yassinebkr/cinematepi5**
- review branch: **integration/cinematepi5-hardening**
- review branch base: **6043e0f**
- upstream repository: **Tiramisioux/cinemate**

The running Pi tree and current upstream have both moved far beyond the old fork base. A direct merge would mix unrelated UI, sensor, settings and service changes in one conflict set.

## Integration rules

For each upstream feature:

1. identify the upstream commits and dependencies
2. compare the upstream implementation with the running Pi implementation
3. back up every file that will be modified
4. adapt the feature to the current Pi 5 architecture rather than blindly cherry-picking it
5. add or adapt regression tests, including failure paths
6. test the integration branch
7. when appropriate, test the same change on the running camera
8. commit the feature as a small reviewable unit
9. keep camera-facing enhancements on the review branch until field-tested

Hardware- or sensor-specific upstream behaviour is not enabled unless it matches the actual camera stack.

## Integrated upstream-derived work

### Custom tuning-file validation

Status: integrated and tested.

A configured tuning override is validated before it is passed to CinePi RAW. Missing files, invalid UTF-8, malformed JSON, VC4/Pi 4 target files and structurally invalid PiSP tuning files fall back to the detected sensor tuning instead of preventing camera startup.

The regression suite also verifies that the launch command receives the valid override only when validation succeeds.

### Degraded/no-camera startup

Status: integration in progress; core safeguards integrated.

The first two parts of upstream's degraded-boot work have been adapted:

- automatic storage pre-roll is skipped when no camera exists
- post-Plymouth camera restart is skipped when discovery reports no camera
- stored sensor mode and dynamic-resolution intent are not overwritten by fabricated fallback values
- an absent camera does not write a fake FPS ceiling
- recording requests are ignored when there is no usable mode table
- resolution commands return safely instead of raising out of the command thread
- white-balance tables still receive a usable fallback curve
- HDMI free-space display does not divide by a zero frame size

These behaviours have dedicated no-camera regression tests.


Camera discovery deliberately retains a **10-second retry window** with one-second polling. This is not a generic delay to optimize away: the IMX283 can take several seconds after boot before it becomes visible to the system. CineMate therefore treats absence as authoritative only after that grace window expires.

If discovery still finds no camera after the full window, CineMate clears only the active runtime sensor identity and mode table (camera_model and res_modes). The reusable sensor database/cache and persisted operator state such as sensor mode, dynamic-resolution intent and FPS ceiling are preserved so the next healthy boot can restore the previous configuration without trusting stale hardware capabilities in the meantime.


The controller follows the same rule for frame rate during degraded startup. With no active camera mode table it selects a usable in-memory FPS from FPS_USER, then FPS, then FPS_LAST, falling back to the configured FPS steps if necessary. It does not publish that fallback through the normal set_fps path, so a no-camera boot cannot rewrite the operator's persisted FPS/FPS_USER values. Normal detected-camera startup keeps the existing reconciliation behaviour.


Storage events also remain camera-independent in degraded mode. A mount or filesystem-profile change may refresh storage/FPS-derived in-memory state, but when no active sensor table exists it does not automatically restart cinepi-raw or start another camera-discovery cycle. The recorder-profile marker is updated in memory and the next explicit or normal camera start uses the current storage profile.


CSI sensor hot-plugging is intentionally unsupported. The camera ribbon and sensor board must only be connected or disconnected with the Pi powered off. After CineMate exhausts the IMX283-aware discovery window and enters degraded/no-camera mode, a camera-only restart is refused; recovery is to restart CineMate or reboot with the sensor already connected. Normal camera-only restart remains available while an active sensor table is present, for example to recover the camera process or rebind preview without changing hardware.


The local GUI also avoids camera-derived capacity math while degraded. If storage is mounted but no usable frame size/FPS exists, the recording-capacity field shows NO CAM instead of dividing by zero or inventing a minutes estimate. NO DISK remains reserved for absent/unmounted storage, and measured storage write speed can still be displayed independently.


A first boot with an empty Redis database follows the same non-mutating rule. Missing FPS state is resolved in memory from the configured conform frame rate (25 fps in the current project settings), snapped to the nearest configured FPS step when needed. Missing shutter state uses 180 degrees in memory. These fallbacks keep the controller and GUI operational but do not seed FPS, FPS_USER, FPS_LAST, SHUTTER_A, sensor-mode or geometry keys into Redis without a working camera.


The local camera-status display is also strict about runtime truth. When CAMERAS is empty, remembered/default camera geometry is not presented as active hardware: the RES field shows NO CAM, resolution/aspect and camera-derived ISO/shutter/WB/exposure readouts show --, and any displayed resolution-switching state is suppressed. Persisted operator values remain untouched and are available again on the next healthy camera boot.


Camera controls are read-only while degraded. ISO, shutter angle (including nominal shutter), FPS, white balance, FPS-double and their increment/decrement paths are rejected before reading or writing camera-control Redis state. This applies uniformly to web, CLI, keyboard and analog/rotary callers because the guard lives in CinePiController. Non-camera controls such as storage, system actions and zoom remain available. Normal camera-control behavior is unchanged when an active sensor mode table exists.


Camera-control modes follow the same degraded lock: shutter-sync, ISO/shutter/FPS/WB free-mode toggles, and combined free-mode configuration are ignored while no active sensor table exists. The IMU calibration confirm routing that shares the shutter-sync control remains available before this guard, so degraded camera state does not break the independent calibration UI.


The web control surface mirrors the controller lock instead of acknowledging rejected commands. When degraded, ISO/shutter/FPS/WB/resolution Socket.IO handlers return before parsing camera-derived Redis state or emitting parameter changes, the initial payload clears remembered camera-control selections, and those selectors are disabled with a NO CAM placeholder. This prevents both fresh-Redis float(None) failures and UI state that falsely suggests a rejected setting was applied.


Internal camera-state paths obey the same invariant: direct FPS correction, nominal-shutter updates, and delayed shutter-transient completion cannot write camera state once the active sensor table is gone. The anamorphic preview factor remains a display preference that may be changed while degraded, but its camera-process restart is skipped until a healthy camera start.

### Recovery console

Status: integrated, hardened and live-tested.

The upstream recovery idea has been adapted as an independent cinemate-recovery.service on port 8080. It remains usable when the main CineMate application, Redis, Flask or the CineMate virtual environment is unavailable.

The local implementation adds:

- strict-JSON validation aligned with this branch's settings.json contract
- installer-generated fallback credentials with blank-token mode locked read-only
- one non-persistent page-level token field for privileged actions
- atomic configuration writes and retained backups
- confirm-or-revert protection for optional config.txt edits
- an explicit service/action allowlist with hotspot-stop protection
- responsive desktop, tablet, phone and phone-landscape layouts
- benign client-disconnect filtering without suppressing unrelated server faults
- dedicated regression tests plus live Pi failure/recovery validation

The recovery console and degraded/no-camera hardening are integrated. The current hardening focus is the authenticated strict-JSON settings editor.

## Upstream features still to evaluate

| Feature family | Assessment |
| --- | --- |
| Settings editor | Integrated and live backend-validated on the hardening branch: dedicated non-persistent token auth, strict-JSON safe writes, protected-secret preservation, revision conflicts, recording/write/buffer/pre-roll lockout, backups, atomic writes, narrowly authorized systemd restart, responsive hybrid layout, and semantic controls across all current settings paths. The startup image flow now includes drag/zoom cropping at the configured HDMI aspect ratio plus an aspect-preserving framebuffer cover fit so images are never stretched. The full semantic registry is live with the IMX283 healthy and settings.json unchanged; final operator visual review remains before promotion. |
| settings.jsonc preservation | Deferred. This hardening phase keeps one strict-JSON contract across runtime, recovery and terminal editing; JSONC requires a separate migration design. |
| Web API, SSE and UDP control | Useful external-control surface; command authorization and destructive actions need review. |
| No-camera startup follow-up | Integrated: degraded startup/state, camera-control locking, truthful local/web UI and fresh-Redis paths are covered by dedicated regression tests. |
| DNG thumbnails | Useful for RAW inspection and playback; must coexist with current proxy Clips workflow. |
| Playback pane | Reconcile with the existing proxy-based Clips interface rather than replacing it. |
| CineMate Log | Relevant to IMX283 but requires dedicated CinemaDNG and Resolve validation. |
| Dynamic resolution v2 | Current branch already contains independent dynamic-resolution work; compare policy by policy. |
| Dual sensors | Large hardware-dependent feature; test only with suitable dual-camera hardware. |
| IMX585 ClearHDR | IMX585-specific. Do not enable on the current IMX283 build. |
| Storage hot-swap safeguards | Compare against the current automount/write-failure implementation. |
| Frame-rate/audio synchronization | Important; compare against the local CinePi RAW phase-lock and audio work. |
| Hardware controls and I2C panes | Integrate selectively around attached hardware. |
| Live log | Useful diagnostics feature with relatively low camera-path risk. |
| Release-image tooling | Important before distributing a complete camera image. |
| Regression suite expansion | Continue importing useful upstream test ideas with every feature. |

## Sensor database caution

Current upstream IMX283 metadata represents a newer driver contract than the proven camera configuration on this Pi. In particular, current upstream includes different full-width modes and packing assumptions.

The review branch therefore retains the locally proven IMX283 mode/packing contract until the newer driver path is validated end to end on the actual sensor. Sensor metadata is treated as executable configuration, not documentation.

## UI integration caution

The Camera and Clips pages in this branch contain substantial independent work:

- responsive mobile and desktop layouts
- real WebGL2 3D LUT rendering
- Camera/Clips LUT state
- Histogram, Waveform and Vectorscope
- adjustable Zebra
- adaptive focus Peaking
- IMU Level overlay
- proxy provenance and playback changes

Upstream live-view changes are therefore mined for individual fixes rather than merged wholesale. Camera-facing UI changes remain on the review branch until manual testing is complete.

## Completion criteria for an upstream port

An upstream-derived feature is considered integrated only when:

- its dependencies are explicit
- its expected failure modes have tests
- the normal camera path still passes regression tests
- relevant live-camera behaviour has been checked
- user documentation reflects the actual implementation
- the change has its own reviewable commit
