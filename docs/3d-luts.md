# Real 3D LUTs in CineMate

This document describes the current CineMate display-LUT implementation used by
both the live Camera page and the Clips player.

The implementation deliberately uses real .cube transforms. It does **not**
approximate a look with CSS filters, SVG tables or hand-written colour
matrices.

## Scope

A CineMate LUT is currently a **display transform only**.

- Camera mode: the LUT is applied to the browser live preview.
- Clips mode: the LUT is applied to the browser proxy player.
- CinemaDNG/RAW frames are not modified.
- The proxy file on disk is not modified.
- Camera and Clips LUT selections are independent.

This is intentional: a monitoring look must never change the recorded RAW
negative unless an explicit future export/bake operation is requested.

## Files and API

Runtime files:

- luts/*.cube - 3D LUT data.
- luts/*.json - optional provenance and colour-space metadata.
- src/module/app/static/js/cube-lut-engine.js - parser and WebGL2 renderer.
- src/module/app/templates/template.html - Camera integration.
- src/module/app/templates/clips.html - Clips integration.
- src/module/app/main/routes.py - LUT catalog/file endpoints and client
  diagnostics.

HTTP endpoints:

- GET /api/luts - catalog of usable LUTs.
- GET /api/luts/<name> - .cube payload.
- POST /api/client-log - renderer diagnostics from the browser.
- GET /api/client-log - recent local renderer diagnostics.

Files whose names start with an underscore are hidden from the normal LUT list
and are reserved for validation.

## Supported .cube syntax

The parser supports real 3D LUTs containing:

- LUT_3D_SIZE
- DOMAIN_MIN
- DOMAIN_MAX
- floating-point RGB rows
- comments and a TITLE

1D-only LUTs are rejected.

The renderer supports tetrahedral interpolation by default and trilinear
interpolation when requested by metadata.

The maximum LUT dimension is checked against the browser GPU
MAX_3D_TEXTURE_SIZE.

## Metadata sidecar

A LUT may have a JSON sidecar with the same basename.

Example:

    {
      "display_name": "CinePi Natural",
      "source": "CinePi",
      "input_space": "Rec.709 display-referred",
      "output_space": "Rec.709 creative look",
      "interpolation": "tetrahedral",
      "official_cinepi": true,
      "verified": true
    }

The .cube file defines numeric RGB mapping but normally does not identify its
intended input and output colour spaces. The sidecar is therefore part of the
colour-management contract, not decorative metadata.

verified=true means CineMate has recorded provenance for that file. It does not
mean the look is suitable for every camera encoding.

## Runtime pipeline

### Catalog and state

The page loads /api/luts and populates the selector.

Camera and Clips keep separate state:

- Camera selection: cameraCubeLut in browser local storage.
- Clips selection: per-clip mapping in clipLuts.

Changing a clip LUT must not change the live Camera LUT.

### Fetch and parse

When a look is selected, cube-lut-engine.js fetches the .cube, validates the
row count and converts it into an in-memory floating-point representation.

The parsed cube is cached in memory for later selections.

At the HTTP layer .cube responses support gzip and browser caching. For
example the current 33x33x33 Golden Hour LUT is roughly 970 kB as plain text
and about 350 kB as the gzip payload.

### GPU representation

The LUT is uploaded as an RGBA8 WebGL2 3D texture.

The browser display path is 8-bit, so a 32-bit floating-point texture did not
provide useful displayed precision here and added mobile-GPU compatibility
risk.

The source frame is a 2D texture:

- Camera: CORS-enabled MJPEG image from port 8000.
- Clips: same-origin proxy video.

### Interpolation shader

The fragment shader normalises source RGB through DOMAIN_MIN and DOMAIN_MAX,
then samples the 3D LUT using tetrahedral or trilinear interpolation.

The full-screen pass uses an explicit WebGL2 VAO/VBO and active position
attribute. This avoids relying on driver-specific behaviour for an
attribute-less draw call.

## Texture orientation: important implementation detail

UNPACK_FLIP_Y_WEBGL is stateful WebGL unpack state.

CineMate therefore applies it explicitly:

    2D camera/video source upload: UNPACK_FLIP_Y_WEBGL = true
    3D LUT volume upload:          UNPACK_FLIP_Y_WEBGL = false

Leaving the flag enabled for the 3D volume corrupts LUT indexing.

A real failure observed during development made this especially clear. For the
Golden Hour LUT:

    expected white (1,1,1) output: 250,247,219
    incorrect GPU output:           250,24,10

250,24,10 is the LUT's pure-red corner (1,0,0), proving that the LUT file and
parser were valid but the 3D texture rows had been rearranged during upload.
The current renderer explicitly separates the 2D source orientation
state from the 3D LUT upload state.

## GPU self-test

Before a selected LUT is allowed to replace the source picture, CineMate runs
a 1x1 GPU self-test:

1. Upload a known white source pixel.
2. Draw it through the selected 3D LUT.
3. Read the output pixel back with readPixels.
4. Compare the result with the white corner stored in the .cube.

This tests the actual browser GPU path: parsing, 3D upload, shader execution,
interpolation and readback.

A self-test failure is considered a real renderer failure. CineMate should
leave the original source visible rather than presenting a black LUT canvas.

## Canvas presentation

The LUT result is rendered to an overlay canvas positioned over the source
image/video.

Only after the first valid LUT frame is drawn does the renderer hide the
underlying source. Disabling the LUT restores the source immediately.

The Clips player uses one consistent player UI whether a LUT is active or not.
LUT loading must never swap between a native video player and a second LUT
player.

## Live-preview CORS requirement

The Camera MJPEG stream is served on port 8000, while the web app uses another
origin/port. WebGL is only allowed to sample that image when both conditions
are met:

1. The MJPEG response includes Access-Control-Allow-Origin.
2. The browser image is created with crossorigin="anonymous".

The current streamer sends:

    Access-Control-Allow-Origin: *

and the Camera image opts into anonymous CORS.

## Colour-space requirement

A mathematically correct LUT can still give the wrong artistic result when the
input encoding is wrong.

Examples:

- an S-Log3 LUT expects S-Log3 input;
- a LogC4 LUT expects LogC4 input;
- a Rec.709 creative LUT expects a display-referred Rec.709-like signal.

CineMate therefore stores input_space and output_space metadata whenever the
LUT source provides enough information.

The current browser preview/proxy pipeline is an ISP-produced display image,
not the original Bayer RAW data. A look intended for a log negative must not
be assumed correct on this preview simply because the file extension is
.cube.

## Official CinePi Rec.709 LUT pack

The normal LUT menu now serves only first-party CinePi looks generated by
tools/generate_cinepi_luts.py:

| Display name | Category | Intent |
| --- | --- | --- |
| CinePi Rec.709 Reference | technical | Identity/reference transform |
| CinePi Natural | natural | Subtle neutral monitoring look |
| CinePi Filmic Neutral | cinematic | Restrained filmic contrast and split tone |
| CinePi Cinema Warm | cinematic | Moderate warm cinematic rendering |
| CinePi Soft Portrait | portrait | Gentle portrait rendering |

Every file is generated deterministically at 33x33x33, has a JSON sidecar and
is listed with SHA-256 in luts/cinepi-official-manifest.json.

Downloaded LUTs used during development were moved to
luts/third_party_dev/. They are intentionally outside the top-level LUT API
scan and are not part of the CinePi shipping set.

See [CinePi Rec.709 and post-production workflow](rec709-post-workflow.md) for
Camera/Clips/Resolve interoperability and the distinction between reference
record-time proxies and approximate regenerated proxies.

## Adding a LUT

1. Put the real file in luts/.
2. Add a sidecar JSON when provenance or colour-space information is known.
3. Reload Camera or Clips.
4. Confirm it appears in /api/luts.
5. Select it and verify that the GPU self-test passes.
6. Compare LOOK: none and the look on neutrals, saturated colours, highlights
   and shadows.
7. Confirm Camera and Clips selections remain independent.

Do not silently convert an unknown internet LUT into a verified CineMate look.
Preserve its original source, licence and intended input colour space.

## Troubleshooting

Useful /api/client-log events include:

- webgl-init
- lut-fetch-start
- lut-loaded
- lut-uploaded
- lut-self-test
- lut-set-active
- lut-first-frame
- lut-render-error

If the selector changes but the image does not, inspect those events.

If a look appears wrong while the self-test passes, investigate colour-space
mismatch before changing the LUT math.

## Related documentation

- [Web preview, responsive UI, PWA and Clips live state](web-preview-responsive-pwa.md)
- [IMX283 colour calibration](imx283-color-calibration.md)
- luts/README.md
