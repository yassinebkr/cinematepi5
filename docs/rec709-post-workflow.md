# CinePi Rec.709 and post-production workflow

This document defines the current CinePi reference display pipeline and how the
official CinePi .cube looks are intended to move between CineMate and post
software such as DaVinci Resolve.

## Reference signal

The live CinePi camera configuration requests a libcamera video stream with:

- BT.709 / Rec.709 primaries
- BT.709 transfer function
- BT.709 YCbCr encoding
- PiSP full-range YCbCr processing

The current 3936x2176 RAW mode aliases the configured low-resolution
1446x800 YUV420 stream as the live preview source.

The important code paths are:

    /home/pi/cinepi-raw/core/rpicam_app.cpp
    /home/pi/cinepi-raw/cinepi/mjpegPreviewStage.cpp

The PiSP backend deliberately uses its rec709_full YCbCr matrix for this
buffer.

## Live Camera preview

The 1446x800 YUV420 ISP stream is JPEG-compressed for the HTTP MJPEG preview.
The RGB/YUV values originate from the libcamera IMX283 tuning and Rec.709 ISP
pipeline.

Current limitation: the MJPEG JPEG files are JFIF and do not yet carry an ICC
profile. Browsers therefore apply their normal untagged-JPEG display behaviour.
This does not change the numeric input expected by the CinePi .cube shader, but
it means the web UI is not yet a substitute for a calibrated reference
monitor.

## Reference Clips proxy

New recordings use the record-time proxy writer in cinepi-raw.

The writer takes the same ordered libcamera YUV420 frames used for preview and
feeds them directly to x264. No second RAW development step is performed.

As of 2026-09-21 those files are explicitly tagged:

    color_primaries = bt709
    color_transfer  = bt709
    color_space     = bt709
    color_range     = pc / full

A successful reference proxy also writes:

    .proxy.json

with:

    pipeline = libcamera-rec709-realtime
    reference_color = true

This is the preferred CineMate Clips source when comparing a CinePi look with
post-production software.

## Regenerated legacy proxy

If a proxy has been deleted, the current background proxy generator can rebuild
one from the CinemaDNG sequence. That path uses the lightweight dng2rgb tool.

At present dng2rgb performs:

- RAW unpack/decompression
- ActiveArea crop
- black subtraction
- AsShotNeutral white balance
- half-resolution RGGB superpixel demosaic
- simple gamma 2.2 encoding

It does **not** reproduce the complete libcamera CCM/tone/ISP pipeline.

Regenerated proxies therefore write .proxy.json with:

    pipeline = dng2rgb-fallback-v1
    reference_color = false

They are playback convenience proxies, not colour-reference proxies.

A future calibration phase may replace this fallback with a fuller
libcamera/DNG colour-development path.

## Official CinePi LUTs

Top-level luts/cinepi-*.cube files are generated entirely by:

    tools/generate_cinepi_luts.py

Current first-party looks:

- CinePi Rec.709 Reference
- CinePi Natural
- CinePi Filmic Neutral
- CinePi Cinema Warm
- CinePi Soft Portrait

The reference LUT is an identity transform. Its purpose is to establish and
test the Rec.709 input contract.

The creative looks all take CinePi Rec.709 display-referred RGB as input and
return the same signal domain with a creative transform.

The generator is deterministic and the SHA-256 values are stored in:

    luts/cinepi-official-manifest.json

## Third-party LUT isolation

Downloaded development LUTs are stored under:

    luts/third_party_dev/

The CineMate API intentionally scans only top-level luts/*.cube. Therefore
third-party development assets do not appear in the normal Camera/Clips LUT
menu and are not part of the official CinePi pack.

## DaVinci Resolve: reference-proxy workflow

For the closest current Camera -> Clips -> Resolve comparison:

1. Record a **new** CinePi clip after the Rec.709 proxy update.
2. Use its record-time proxy, not a regenerated fallback proxy.
3. Import proxy.mp4 into Resolve.
4. Confirm Resolve sees BT.709 metadata and Full data levels. If automatic
   interpretation is wrong, set the clip Data Levels to Full manually.
5. Use a normal SDR Rec.709 monitoring/output setup.
6. Install the same cinepi-*.cube file used in CineMate.
7. Apply that LUT to the clip without an additional input transform in front of
   it.

The same .cube data is then being applied to the same Rec.709 display-referred
signal domain.

For a strict numeric A/B test, avoid adding automatic colour-space transforms,
contrast nodes or output-look nodes ahead of the CinePi LUT.

## CinemaDNG workflow

CinemaDNG is the camera negative, not the already-developed Rec.709 preview.

Resolve must first develop the RAW data. CinePi DNG files contain sensor
black/white metadata, AsShotNeutral and colour-matrix data derived from camera
metadata, but Resolve's RAW development is not the same code path as the
libcamera PiSP ISP.

Therefore:

    DNG -> Resolve RAW development -> CinePi LUT

can use the exact same creative LUT, but the pre-LUT image is not yet
guaranteed pixel-identical to:

    IMX283 -> libcamera PiSP -> CinePi LUT

That final RAW-development parity is a separate future colour-calibration
project. It must not be falsely solved by baking an arbitrary correction into
the creative LUT.

## What Rec.709 means here

Rec.709 is the technical interchange/reference signal used by the CinePi
monitoring path. It is not itself a cinematic look.

The official CinePi creative LUTs sit *after* that technical baseline:

    IMX283 RAW
      -> libcamera IMX283 tuning / ISP
      -> CinePi Rec.709 reference signal
      -> optional CinePi creative .cube

This separation is what makes the creative files portable to post software.

## Distribution and licensing

The official cinepi-*.cube files contain no downloaded third-party LUT data.

The CineMate repository currently has no top-level public software licence.
Consequently the LUT metadata currently says pending-project-license. Before a
public/open-source release, choose the project licence deliberately and update
the LUT release metadata.

Do not ship luts/third_party_dev as first-party CinePi assets.
