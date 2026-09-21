# CineMate / CinePi LUT directory

CineMate serves real 3D .cube LUTs from the **top level** of this directory.

## Official CinePi shipping set

The normal Camera and Clips LUT menus currently expose only the first-party
CinePi pack:

- CinePi Rec.709 Reference
- CinePi Natural
- CinePi Filmic Neutral
- CinePi Cinema Warm
- CinePi Soft Portrait

These files are generated deterministically by:

    tools/generate_cinepi_luts.py

Hashes and titles are recorded in:

    cinepi-official-manifest.json

The complete first-party pack for post-production is available from CineMate:

    /api/luts/official-pack.zip

The ZIP contains the exact .cube files used by the camera UI, their JSON
metadata, the SHA-256 manifest and the Rec.709/Resolve workflow document.

## Validation fixture

_identity_17.cube is an internal validation LUT and is hidden from the normal
selector.

## Third-party development LUTs

Downloaded experimental LUTs are preserved under:

    third_party_dev/

They are intentionally not scanned by the normal LUT API and are not part of
the CinePi shipping set.

Do not move a third-party LUT into the top-level directory for a public release
unless its licence explicitly permits redistribution as part of CinePi.

## Input contract

The official first-party looks expect the CinePi Rec.709 display-referred
signal documented in:

    docs/rec709-post-workflow.md

A LUT intended for S-Log3, LogC, BMD Film or another log/wide-gamut encoding
must not be applied directly to this Rec.709 signal without the appropriate
technical input transform.

## Implementation

Full renderer, WebGL2, interpolation, CORS, GPU self-test and troubleshooting
documentation:

    docs/3d-luts.md

Colour-pipeline and DaVinci Resolve workflow:

    docs/rec709-post-workflow.md

Sensor calibration documentation:

    docs/imx283-color-calibration.md

## Licensing

The CinePi-generated LUT data contains no downloaded third-party LUT data.
However, the repository currently has no top-level public LICENSE file.

See:

    CINEPI-LUT-LICENSING.md

before a public release.
