# Settings editor

The structured settings editor is a browser UI for the same strict JSON file used by CineMate:

    /home/pi/cinemate/src/settings.json

It does not edit config.txt, storage, takes, playback, or I2C hardware. Those remain separate workflows. This narrower scope is intentional during hardening.

## Open the editor

Use:

    http://cinepi.local:5000/settings-editor/

The page itself is only a locked shell. It does not contain settings data.

The settings API requires a dedicated settings-editor token. The browser keeps the token only in JavaScript memory for the current page. It is not written to cookies, localStorage, sessionStorage, the URL, or settings.json.

Reloading or navigating away locks the editor again.

## If you forget the token

On the Pi:

    cinemate-settings-editor-token show

To replace it:

    sudo cinemate-settings-editor-token rotate --group pi

Rotation takes effect immediately because the web editor reads the token configuration for each authenticated request.

The credential is stored at:

    /etc/cinemate-settings-editor.conf

The installer creates it as root:pi mode 0640, generates a cryptographically random token when none exists, and preserves an existing token across installs and updates.

The settings-editor token is deliberately separate from the recovery-console token.

## Semantic widgets

The editor can use optional x-cinemate-ui metadata from settings.schema.json to select controls that understand the meaning of a setting. These annotations affect presentation only; config_loader remains the runtime validation authority and the generic JSON-type renderer remains the fallback.

welcome_image is the reference semantic widget. Its Upload image control accepts an image, validates it through Pillow, applies EXIF orientation, normalizes it to RGB PNG, and stores the content-addressed asset under ~/.local/share/cinemate/settings-assets/. Uploading does not modify settings.json; the new path remains a pending editor change until Save changes is used.

Only files inside that managed asset directory can be previewed through the editor API. Existing external image paths remain valid settings but are not exposed through the preview endpoint.

After validating the image widget, the same semantic metadata layer was extended across the current settings file. Primitive preset arrays use structured list editors; hardware button/switch/encoder arrays use repeatable object cards; controller actions have method/argument controls; ADC channels, policies and fixed choices use selects; server-side resource locations use explicit path controls; and advanced free-form objects such as custom sensor modes retain a deliberate JSON-object editor. Every current settings path has semantic metadata, while unknown future keys still fall back to the generic renderer.

## What the page shows

After authentication, the current strict JSON document is rendered as nested sections:

- booleans as switches
- numbers as numeric inputs
- strings as text inputs
- password fields as masked inputs
- arrays as strict-JSON array editors
- nested objects as collapsible groups

The search field filters by settings path.

The View JSON action shows the editor state that would be submitted. Protected key names containing token, secret, or credential are never sent to the browser. If such keys exist in the file, the server preserves them during saves.

## Save discipline

Saving is fail-closed.

The server:

1. verifies the settings-editor token with a constant-time comparison
2. refuses the save while CineMate is recording, writing, draining buffered frames, or buffering
3. verifies that the file revision still matches the revision the browser loaded
4. merges the submitted settings over the raw file on disk so fields the page did not render survive
5. renders strict JSON
6. validates the candidate through CineMate's hardened config_loader
7. re-checks camera/storage activity and the on-disk file immediately before writing
8. creates a private backup
9. atomically replaces settings.json and fsyncs the directory

If another writer changes settings.json while the page is open, Save returns a conflict and asks the operator to reload instead of overwriting the newer file.

Backups created by the web editor are stored under:

    ~/.local/state/cinemate/settings-backups/

The current editor does not auto-restart CineMate after Save. This avoids a delayed restart racing a newly started take. Save reports that a restart is still needed.

## Restart CineMate

Restart CineMate is a separate action.

It is disabled while the form contains unsaved edits and is refused whenever any of these runtime states is active:

- recording
- writing
- buffered-frame writing
- buffering

The server checks activity again at the timer boundary immediately before invoking the restart. If activity starts after the button was pressed, the restart is cancelled rather than interrupting the take.

Restart is systemd-managed. The web process never execs itself in place and is not granted general sudo access. A root-owned /usr/local/bin/cinemate-restart-service helper can only validate its installation or queue a restart of cinemate-autostart.service; sudoers grants the CineMate service user permission to invoke only that helper.

## Strict JSON

The structured editor uses the same strict-JSON contract as normal CineMate startup, the terminal editsettings helper, and the recovery console.

Comments and trailing commas are rejected.

settings.schema.json is still incomplete and is not treated as the runtime authority. The hardened config_loader validates known runtime container shapes and values while preserving compatibility with unknown future keys.

## Recovery boundary

If the live settings file is already malformed or structurally unsafe, the normal settings editor refuses to edit it. Use the independent recovery console on port 8080 or the local editsettings helper instead.

The recovery console remains intentionally independent of the main Flask app and has its own credential.
