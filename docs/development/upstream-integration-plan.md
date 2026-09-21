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

## Upstream features still to evaluate

| Feature family | Assessment |
| --- | --- |
| Settings editor | High value; large subsystem. Integrate after configuration format is finalized. |
| settings.jsonc preservation | High value for human-edited settings; requires migration design from current JSON runtime. |
| Recovery console | High operational value; good next isolated service feature. |
| Web API, SSE and UDP control | Useful external-control surface; command authorization and destructive actions need review. |
| No-camera startup follow-up | Continue testing the remaining degraded-state paths before moving on. |
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
