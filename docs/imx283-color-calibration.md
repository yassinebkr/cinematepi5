# IMX283 colour calibration

This document separates sensor/ISP calibration from creative LUT work.

A 3D creative LUT cannot repair a badly calibrated RAW-to-display pipeline.
The intended order is:

    sensor RAW
      -> black-level / defect correction
      -> lens shading
      -> white balance
      -> colour correction matrix
      -> tone/gamma / display encoding
      -> optional creative display LUT

## Current CineMate IMX283 state

The running Pi explicitly uses:

    /home/pi/libcamera/src/ipa/rpi/pisp/data/imx283.json

As of 2026-09-20, the previous compact experimental tuning has been replaced
with the full IMX283 PiSP tuning tracked by the **same local libcamera checkout
used by this camera build**.

The experimental file was preserved byte-for-byte at:

    /home/pi/imx283-tuning-backups/imx283-experimental-20260920-231603.json

The active baseline contains:

- black_level 3200
- bayes-enabled AWB
- 16 ct_curve points in this local libcamera revision
- 19 temperature-dependent CCM entries
- the additional sensor/ISP tuning blocks that had been removed by the
  experimental file

CineMate successfully reads that ct_curve at startup and now generates its
manual Kelvin WB gains from the sensor tuning instead of the fallback table.

At the current 3300 K setting the active values are:

    wb_user = 3300
    cg_rb   = 1.3,2.5

and cinepi-raw was verified running with:

    --awbgains 1.3,2.5
    --tuning-file /home/pi/libcamera/src/ipa/rpi/pisp/data/imx283.json

This file is a **baseline**, not a claim that the particular IMX283 module and
optical stack are fully colour-calibrated.

## Important upstream finding

The current public raspberrypi/libcamera repository already contains a
substantially fuller **PiSP IMX283 tuning file**, including:

- calibrated rpi.awb.ct_curve
- AWB priors and modes
- multiple CCMs across colour temperature
- ALSC calibration
- noise, GEQ, denoise and other PiSP blocks

Source:

    https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/pisp/data/imx283.json

Its current PiSP ct_curve is:

    2500, 0.9437, 0.2866
    2820, 0.8496, 0.3541
    2830, 0.8309, 0.3681
    2885, 0.8183, 0.3778
    3601, 0.6946, 0.4786
    3615, 0.6929, 0.4801
    3622, 0.6905, 0.4821
    4345, 0.6012, 0.5628
    4410, 0.5956, 0.5682
    4486, 0.5892, 0.5743
    4576, 0.5794, 0.5837
    5672, 0.5232, 0.6392
    5710, 0.5188, 0.6436
    6850, 0.4862, 0.6773

This gives us a credible sensor-specific baseline without buying a colour
target first.

It must still be validated on the actual camera module because the IR-cut
filter, cover glass, lens shading and other optical-stack differences affect
colour response.

## What ct_curve actually contains

Raspberry Pi's AWB tuning defines the curve as triples:

    [T, r, b]

where:

- T is colour temperature in kelvin;
- r is the red neutral-response coordinate used by AWB;
- b is the blue neutral-response coordinate used by AWB.

In libcamera's AWB implementation, manually setting a colour temperature uses:

    red_gain   = 1 / r(T)
    green_gain = 1
    blue_gain  = 1 / b(T)

This is also how CineMate currently interprets the curve.

For practical neutral-target measurements, the values correspond to the
sensor's approximately normalised neutral RAW response:

    r ~= R / G
    b ~= B / G

after black subtraction and before white-balance gains.

Example from the current upstream PiSP IMX283 curve:

| CCT | r | b | red gain ~= 1/r | blue gain ~= 1/b |
| ---: | ---: | ---: | ---: | ---: |
| 2500 K | 0.9437 | 0.2866 | 1.06 | 3.49 |
| 2885 K | 0.8183 | 0.3778 | 1.22 | 2.65 |
| 3601 K | 0.6946 | 0.4786 | 1.44 | 2.09 |
| 4410 K | 0.5956 | 0.5682 | 1.68 | 1.76 |
| 5672 K | 0.5232 | 0.6392 | 1.91 | 1.56 |
| 6850 K | 0.4862 | 0.6773 | 2.06 | 1.48 |

These are **not spectral-sensitivity curves**. They are a compact calibration
of where neutral illuminants fall in the camera's red/green and blue/green
response space.

## Why low-K shadows can turn green

Several mechanisms can combine:

1. At low colour temperature the blue channel needs a large gain.
2. Shadows sit only slightly above the sensor black floor.
3. A small R/Gr/Gb/B black-offset error becomes a large fraction of the
   remaining signal.
4. A strong CCM can amplify the residual channel error.
5. The active baseline now has temperature-dependent CCMs, so the earlier
   single-4000 K experimental matrix is no longer the expected cause.
6. The active baseline also contains a ct_curve and CineMate derives manual
   Kelvin gains from it, so the earlier fallback-table limitation no longer
   applies.

For this reason a green cast that grows in the shadows is not good evidence
that "green gain is wrong". It may be a black-offset + WB + CCM interaction.

## Existing Dark cal experiment

The current Dark cal button captures a short capped-lens RAW clip and runs:

    /home/pi/darkcal/darkcal.py

The saved result from 2026-07-10 reports:

    frames:     10
    size:       3936 x 2176
    black:      197.8
    noise MAD:  1.48
    threshold:  257.8
    candidates: 5418

The DNG data is 12-bit. Raspberry Pi's SensorBlackLevels convention and tuning
black levels are represented on a 16-bit scale. Therefore:

    197.8 * 16 = 3164.8

which is close to the configured value of 3200.

So the existing dark calibration is **not useless or obviously bad**. It
actually supports the current global black-level order of magnitude.

However, it is insufficient for colour calibration because it currently
computes one median over the whole Bayer mosaic.

It does not yet measure separately:

    R, Gr, Gb, B

and it does not build a black-level model versus analogue gain / ISO or sensor
temperature.

That matters because a per-channel residual of only a few 12-bit code values
can become visible after large low-K blue gains and a strong CCM.

The current hot-pixel list is also strongly concentrated in some edge columns,
for example x around 80-87. Active-area/optical-black boundaries and
packing/crop geometry should therefore be excluded before interpreting every
candidate as a real defective photosite.

## Improved dark calibration plan

**Status:** deferred for now. The existing Dark cal remains available and its
saved result is preserved. When sensor calibration work resumes, this pipeline
should be enhanced rather than replaced by ad-hoc visual black-level tuning.


The next dark-calibration revision should:

1. Capture multiple dark RAW frames with the lens fully capped.
2. Record exposure, analogue gain/ISO and sensor temperature.
3. Exclude non-active border/optical-black regions.
4. Split the Bayer mosaic into R, Gr, Gb and B planes.
5. Reject hot pixels before estimating the black floor.
6. Store per-plane median and robust noise statistics.
7. Repeat at several gains/ISOs.
8. Verify whether one 3200 tuning value is adequate or whether remaining
   per-channel offsets need handling elsewhere in the RAW/DNG pipeline.

The first useful outputs should look like:

    ISO/gain, temperature,
    black_R, black_Gr, black_Gb, black_B,
    noise_R, noise_Gr, noise_Gb, noise_B

This requires no colour chart.

## Calibrating ct_curve without an expensive colour chart

A 24-patch or 140-patch colour target is **not required** to measure ct_curve.

The CT curve only needs a spectrally neutral target under illuminants with
known colour temperature.

A practical workflow is:

1. Start with the official upstream IMX283 PiSP curve.
2. Use a reasonably neutral matte grey/white reference.
3. Illuminate it uniformly.
4. Capture RAW, not the processed preview.
5. Subtract the per-channel black levels.
6. Average a large central region for each Bayer plane.
7. Compute:

       G = mean(Gr, Gb)
       r = R / G
       b = B / G

8. Record [actual_CCT, r, b].
9. Repeat at several temperatures.
10. Fit/interpolate a smooth curve.

Three to five good illuminants are already useful for validation. More points
improve interpolation.

### Illuminant caveat

The number printed on a cheap LED lamp is not a laboratory CCT reference.
LED spectral power distributions can be spiky and two lamps with the same CCT
can produce different camera RGB ratios.

For inexpensive experiments:

- tungsten/incandescent sources are useful at low CCT because their spectra
  are close to a Planckian radiator;
- natural daylight can provide a useful high-CCT point when conditions are
  stable;
- high-quality photographic LEDs can be used for intermediate checks, but
  nominal CCT should not be treated as metrology.

Because we already have an official IMX283 PiSP curve, the immediate goal
should be **validation**, not rebuilding the curve from zero.

## CCM calibration is a different problem

A colour correction matrix maps the camera's device RGB response toward a
target colour space.

Unlike ct_curve, a good CCM needs chromatic information. A neutral grey card
cannot solve a full 3x3 CCM.

Without a measured colour target, the safest path is:

1. Use the current official Raspberry Pi IMX283 CCM set as the baseline.
2. Validate neutrals and common colours.
3. Do not fit a new matrix from visually chosen colours.
4. Later, if necessary, borrow or buy a measured target and run a repeatable
   calibration.

A printed home/office chart is not a trustworthy CCM reference because printer
inks and paper have unknown spectral reflectance. A phone/monitor RGB chart is
also not a full substitute: display primaries are narrow-band emitters and can
produce metameric camera responses unlike real objects.

## About published IMX283 spectral-response claims

Do not use an unsourced "exact IMX283 spectral table" as a direct tuning input.

Sony public sensor documentation does not expose enough CFA spectral data to
justify treating a reconstructed table from related 1-inch sensors as exact.
Even sensors with similar photodiodes can differ because of CFA dyes,
microlenses, cover glass and the module's IR-cut filter.

More importantly, even a correct sensor QE/CFA spectral curve would not by
itself give a production CCM. A spectral calibration also needs the optical
stack, illuminant spectra, target reflectance spectra and the intended colour
space.

For CineMate, the libcamera IMX283 ct_curve and CCM tuning data are much more
directly relevant than guessed wavelength peaks.

## Current calibration strategy

For now:

1. Use the full local-libcamera IMX283 PiSP tuning as the camera baseline.
2. Keep LOOK: none as the neutral monitoring reference.
3. Treat the official CinePi LUT pack as creative Rec.709 looks, not sensor
   calibration.
4. Defer Dark cal changes while preserving the existing result and script.
5. Later, enhance Dark cal to per-Bayer-channel and multi-gain measurements.
6. For final CCM work, use a genuinely measured high-quality colour target
   rather than a cheap printed clone or an improvised screen target.
7. Treat the libcamera IMX283 AWB/CCM data as a strong starting point but not
   as a substitute for module-specific calibration of the actual sensor,
   IR-cut/cover-glass stack and lens system.

This keeps the camera on a defensible known baseline while leaving the full
calibration pipeline for a dedicated later phase.

## Primary references

Raspberry Pi Camera Algorithm and Tuning Guide:

    https://datasheets.raspberrypi.com/camera/raspberry-pi-camera-guide.pdf

Current Raspberry Pi libcamera PiSP IMX283 tuning:

    https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/pisp/data/imx283.json

Raspberry Pi libcamera AWB implementation:

    https://github.com/raspberrypi/libcamera/blob/main/src/ipa/rpi/controller/rpi/awb.cpp

Related CineMate documentation:

- [Real 3D LUTs in CineMate](3d-luts.md)
- [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md)
