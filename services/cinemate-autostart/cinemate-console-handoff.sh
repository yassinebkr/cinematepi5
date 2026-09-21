#!/usr/bin/env bash

set -euo pipefail

shutdown_targets=(
    halt.target
    kexec.target
    poweroff.target
    reboot.target
    shutdown.target
)

systemd_manager_stopping() {
    local state
    state=$(/bin/systemctl is-system-running 2>/dev/null || true)
    [[ "${state}" == "stopping" || "${state}" == "offline" ]]
}

cinemate_restart_in_progress() {
    local _job_id unit job_type _job_state _rest

    while read -r _job_id unit job_type _job_state _rest; do
        [[ -z "${unit:-}" ]] && continue
        if [[ "${unit}" == "cinemate-autostart.service" ]]; then
            case "${job_type}" in
                restart|try-restart|reload-or-restart)
                    return 0
                    ;;
            esac
        fi
    done < <(/bin/systemctl list-jobs --no-legend --no-pager 2>/dev/null || true)

    return 1
}

shutdown_job_in_progress() {
    local unit

    while read -r _job_id unit _job_type _job_state _rest; do
        [[ -z "${unit:-}" ]] && continue

        for target in "${shutdown_targets[@]}"; do
            if [[ "${unit}" == "${target}" ]]; then
                return 0
            fi
        done
    done < <(/bin/systemctl list-jobs --no-legend --no-pager 2>/dev/null || true)

    return 1
}

if cinemate_restart_in_progress; then
    # A restart transaction already contains the next CineMate start job.
    # Starting getty@tty1 here would conflict with that queued start and can
    # cancel the restart. Keep tty1 owned by CineMate across the restart.
    exit 0
fi

if systemd_manager_stopping || shutdown_job_in_progress; then
    /bin/systemctl --no-block start plymouth-start.service >/dev/null 2>&1 || true
    if command -v plymouth >/dev/null 2>&1; then
        plymouth change-mode --shutdown >/dev/null 2>&1 || true
        plymouth show-splash >/dev/null 2>&1 || true
    fi
    exit 0
fi

/bin/systemctl --no-block --no-ask-password start getty@tty1.service >/dev/null 2>&1 || true
