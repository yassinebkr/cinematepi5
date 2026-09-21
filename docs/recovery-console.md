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
- controlled restart or stop actions for an explicit service allowlist

It is not a replacement for the normal CineMate web interface. Use it when the normal interface on port 5000 is unavailable or the camera application fails early during startup.

## Opening the console

On the camera hotspot, browse to:

    http://10.42.0.1:8080

When mDNS is available, the same service can normally be reached at:

    http://cinepi.local:8080

The recovery service is intentionally independent of cinemate-autostart.service. Restarting or crashing CineMate therefore does not stop the recovery web server.

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

The token is entered into the recovery form when saving settings or requesting an allowed service action.

If no token is configured, the console becomes **read-only**. Mutating requests are denied instead of becoming unauthenticated.

A reinstall preserves an existing non-empty token rather than silently rotating it.

## Service allowlist

The console does not pass arbitrary service names to systemctl. Only these services are accepted:

- cinemate-autostart
- wifi-hotspot
- storage-automount

Only start, stop and restart are valid actions.

The hotspot has additional protection: it may be restarted, but the recovery console refuses to stop it. This avoids cutting off the operator's only connection to the camera.

## Editing settings.json

The recovery editor works on the configuration actually used by this branch:

    /home/pi/cinemate/src/settings.json

A save follows a validation ladder:

1. use the system Python interpreter with CineMate's own module.config_loader
2. if that validator cannot run, use the Python standard-library JSON parser
3. if no validator is available, permit the repair as explicitly **unvalidated**

The final rung is intentionally fail-open because a broken settings file may be the reason the recovery console is needed. Safety comes from making a backup before the write.

This branch uses strict JSON. JSONC comments and trailing commas are therefore rejected rather than accepted by the fallback validator.

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

The service first looks for an explicit system.recovery object in src/settings.json. If that block does not exist, it uses:

    /etc/cinemate-recovery.conf

If neither source is usable, built-in defaults keep the diagnostic pages available, but write actions remain disabled because no token is available.

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
