# Recovery console

The recovery console is a small standalone web service on port **8080** for situations where the main CineMate application cannot start.

It deliberately does not depend on Flask, Redis, the CineMate virtual environment or cinemate-autostart.service. It uses the system Python standard library and runs as its own systemd service, so a failure in the main camera application does not remove the diagnostic interface.

## What it is for

The recovery console provides a limited maintenance surface from a phone or computer connected to the camera:

- current service states and system facts
- the most recent CineMate startup-failure message
- recent service logs
- editing and validating src/settings.json
- optional editing of /boot/firmware/config.txt
- controlled restart actions for an explicit service allowlist

It is not a replacement for the normal CineMate web interface. Use it when the normal interface on port 5000 is unavailable or the camera application fails early during startup.

## Opening the console

On the camera hotspot, browse to:

    http://10.42.0.1:8080

When mDNS is available, the same service can normally be reached at:

    http://cinepi.local:8080

The recovery service is intentionally independent of cinemate-autostart.service. Restarting or crashing CineMate therefore does not stop the recovery web server.

## Responsive interface

The recovery UI is intentionally self-contained: its HTML and CSS are emitted by the standard-library service and do not require JavaScript, a frontend bundle, Flask or the CineMate virtual environment.

The status page adapts to the device instead of assuming a fixed viewport:

- desktop uses a near-full-width dashboard with compact service rows and a separate system-status panel
- tablet collapses the dashboard to a single main column where necessary
- phone uses stacked controls with full-width touch targets
- phone landscape has a dedicated compact-height layout
- navigation shows the active page explicitly

The desktop shell is capped at 112 rem to use normal monitors efficiently without stretching the dashboard indefinitely on ultrawide displays.

## Read-only diagnostics

The diagnostic pages remain reachable without the recovery token:

| Page | Purpose |
| --- | --- |
| / | Service states, uptime, storage information and recovery configuration state |
| /health | Lightweight health endpoint |
| /why | Last persisted CineMate startup-failure message |
| /log | Recent journal entries for allowlisted CineMate services |

Keeping these pages readable without authentication means a lost token does not prevent diagnosis.

## Write protection and recovery token

Anything that changes the system requires the recovery token.

The installer generates a random token with Python's secrets module and stores it in:

    /etc/cinemate-recovery.conf

The file is owned by root and installed with mode 0600.

To view the token locally over SSH:

    sudo awk -F= '$1 == "token" {print $2}' /etc/cinemate-recovery.conf

The console presents **one page-level access-token field** for privileged actions. The same field is used by every mutating control on that page, including service restarts and configuration saves.

The token is deliberately not stored in cookies, localStorage or sessionStorage. Navigating to another page or reloading the current page clears it and requires re-entry. This keeps the recovery surface stateless and avoids leaving a privileged token behind in the browser.

If no token is configured, the console becomes **read-only**. Mutating requests are denied instead of becoming unauthenticated.

A reinstall preserves an existing non-empty token rather than silently rotating it.

## Service allowlist

The console does not pass arbitrary service names to systemctl. Only these services are accepted:

- cinemate-autostart
- wifi-hotspot
- storage-automount

At the server boundary, only start, stop and restart are accepted actions. The web interface intentionally exposes **Restart** only; it does not surface generic Start/Stop controls.

The hotspot has additional protection: even if a stop request is sent directly, the recovery console refuses it. This avoids cutting off the operator's only connection to the camera.

## Editing settings.json

The recovery editor works on the configuration actually used by this branch:

    /home/pi/cinemate/src/settings.json

A save uses a fail-closed validation ladder:

1. run CineMate's own config_loader against the candidate; syntax, UTF-8, root shape and known runtime structure must pass
2. if that validator exits unexpectedly, run the same validator against a known-good empty object
3. only when the known-good self-test also fails is the CineMate validator considered unavailable, allowing fallback to Python's strict standard-library JSON parser

A candidate-specific loader failure is therefore rejected rather than silently downgraded to syntax-only validation. The fallback remains available when CineMate's interpreter/import path is genuinely broken, which preserves the recovery console's independence.

This branch uses strict JSON everywhere. Comments and trailing commas are rejected by normal startup, the recovery editor and the terminal editsettings helper.

## Atomic writes and backups

Configuration writes use a temporary file in the destination directory, flush the data, replace the target atomically, and fsync the directory where possible.

Before replacing an existing configuration file, the console writes a backup under:

    /var/lib/cinemate/backups/

Backup retention preserves the oldest known backup and the most recent generations. Two writes in the same second receive unique backup names.

## Editing config.txt

Editing /boot/firmware/config.txt is disabled by default.

The fallback configuration contains:

    allow_config_txt=false

Enable this capability only when it is actually required.

When config.txt editing is enabled, a save creates a backup and arms a confirm-or-revert timer. After rebooting, confirm the new configuration from the recovery console. If the change is not confirmed before the timeout, the previous config is restored and the Pi is rebooted.

This protects against changes that allow Linux to boot but leave the camera unusable.

It cannot recover a change that prevents the Pi from reaching userspace at all. In that case the boot medium must be repaired externally.

## Configuration fallback

Recovery configuration is resolved independently of the main camera process.

The service reads system.recovery from src/settings.json when that file is valid. Values present there override the installer fallback; omitted values, including the token, can be inherited from:

    /etc/cinemate-recovery.conf

If settings.json is malformed or missing, the fallback file becomes the complete recovery configuration. If neither source is usable, built-in defaults keep the diagnostic pages available but mutating actions remain locked because no token is available.

This avoids a circular dependency where a broken or older settings file would prevent access to the service intended to repair it.

## systemd service

The service is:

    cinemate-recovery.service

Useful service commands are:

    sudo systemctl status cinemate-recovery
    sudo systemctl restart cinemate-recovery
    journalctl -u cinemate-recovery -f

It runs as root because its restricted maintenance functions include service control and optional config.txt writes. The HTTP handler compensates for that privilege with a small standard-library-only runtime, a fixed service/action allowlist, token checks on mutating requests, atomic writes and action logging.

## Installing manually

The normal CineMate installer enables the recovery service by default. It can be disabled during installation with:

    ENABLE_RECOVERY_CONSOLE_SERVICE=0

On an existing checkout, install and enable only this service with:

    sudo make -C /home/pi/cinemate/services enable-cinemate-recovery

A valid /etc/cinemate-recovery.conf should be present before enabling write actions.

## Failure boundaries

The recovery console is designed to survive failures in:

- CineMate application startup
- Redis
- Flask and other CineMate Python packages
- the CineMate virtual environment
- malformed settings.json

It cannot recover a Pi that never boots far enough to start systemd, a failed boot device, or a network failure that prevents all access to the Pi.

## HTTP failure logging

Phone and browser clients can close keep-alive connections abruptly while navigating, sleeping or changing networks. The threaded recovery server suppresses only the routine ConnectionResetError and BrokenPipeError cases at the server boundary so they do not flood the journal with misleading tracebacks.

Other server exceptions are not suppressed and continue through Python's normal error-reporting path.
