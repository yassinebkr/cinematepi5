# CinePi monitoring tools

For camera-operation instructions, examples and visual guides, see [Monitoring tools — operator guide](monitoring-tools-user-guide.md).


CineMate provides lightweight on-camera exposure, colour, focus and orientation
aids derived from the live libcamera Rec.709 preview.

## Measurement domain and LUTs

The exposure/focus analysis uses the source CinePi Rec.709 preview.

When a creative 3D LUT is selected, Zebra and Focus Peaking are composited
above the LUT canvas so they remain visible. Their measurements intentionally
remain source-referred: a creative LUT must not hide source clipping or change
which source edges are judged in focus.

Histogram, Waveform, Vectorscope and ETTR likewise describe the source preview.

A future optional SOURCE / DISPLAY-LUT analysis mode can be added for users
who want scopes to inspect the graded display image.

## Signal range

PiSP supplies the CinePi Rec.709 preview as full-range YCbCr internally. After
JPEG/browser decode the monitoring code receives full-range RGB values in
0..255.

Monitoring v2 therefore computes BT.709 luma directly from RGB:

    Y' ~= 0.2126 R' + 0.7152 G' + 0.0722 B'

The old code incorrectly remapped this RGB-derived value as if it were still
limited-range 16..235. That made highlight thresholds and ETTR too aggressive.

## Zebra

Current default:

    95 IRE

Behaviour:

- striped red: source luma >= 95 IRE
- solid red: one or more source RGB channels >= 254

The separate solid clipping state is important because a saturated colour can
clip one channel before luma reaches the zebra threshold.

Possible future control: selectable 70 / 90 / 95 / 100 IRE thresholds.

## Focus Peaking

Peaking v2 no longer uses a simple two-pixel difference.

Pipeline:

1. BT.709 luma
2. separable 3x3 Gaussian denoise
3. Sobel horizontal + vertical gradient
4. estimate an image noise floor from the gradient distribution
5. derive an adaptive threshold
6. local-maximum suppression
7. cyan one-pixel contour overlay, scaled with the preview

This is substantially less sensitive to high-ISO pixel noise and generates
thinner contours around genuinely high-frequency detail.

The computed threshold/noise floor is exposed in the PEAK button tooltip for
diagnostics.

## Histogram

The histogram now shows:

- red channel
- green channel
- blue channel
- white BT.709 luma

It uses 128 bins and logarithmic vertical scaling so sparse highlight/shadow
information remains visible instead of being crushed by a large midtone peak.

## Waveform

The waveform uses full-range BT.709 luma and a logarithmic density display.

Reference guides are drawn at:

- 0 IRE
- 18 IRE
- 50 IRE
- 70 IRE
- 90 IRE
- 100 IRE

The backing store was increased from 120x80 to 160x100 while retaining the
compact UI display size.

## Vectorscope

Vectorscope v2 derives chroma using Rec.709 Y'CbCr coefficients instead of the
previous approximate red/blue deltas.

It adds:

- centre cross
- nominal chroma circle
- R, Y, G, C, B and M targets
- an approximate 123-degree skin-tone guide
- logarithmic density rendering

The scope remains a compact monitoring aid, not a laboratory compliance
instrument.

## ETTR advisor

ETTR now evaluates the brightest RGB channel, not only luma.

If any sampled pixel reaches >=254 in R, G or B it reports the percentage of
sampled pixels with channel clipping.

Otherwise it estimates headroom from the 99.9th percentile of the maximum RGB
channel and reports the approximate remaining exposure in EV.

This makes saturated-colour clipping visible earlier and avoids the previous
limited-range luma error.

## LEVEL

The web LEVEL HUD now consumes both calibrated roll and pitch from the IMU.

- roll rotates the horizon
- pitch moves the horizon vertically
- +/-5-degree pitch references are shown
- green level state requires both roll and pitch within 0.7 degrees
- shake/angular-rate meter is retained

set zero already calibrates both roll and pitch.

## Performance

Image-analysis runs on a 480x270 working frame rather than the full preview.
This keeps browser CPU use bounded while the actual camera stream and 3D LUT
continue at display resolution.
