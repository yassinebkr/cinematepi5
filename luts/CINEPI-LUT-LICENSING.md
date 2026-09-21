# CinePi LUT licensing status

The cinepi-*.cube files in this directory are generated entirely by
tools/generate_cinepi_luts.py. They do not contain third-party LUT data.

They are intended to be first-party CinePi assets and safe for CinePi to ship
commercially once the project chooses its public release licence.

The repository currently has no top-level LICENSE file. Therefore the public
release licence is intentionally marked pending-project-license rather than
silently choosing a legal licence on behalf of the project owner.

Downloaded third-party development LUTs are stored under
luts/third_party_dev/. CineMate's LUT API only scans top-level luts/*.cube,
so those files are not offered by the normal Camera/Clips UI and must not be
included as first-party CinePi assets in a release image.
