# Makefile for cinemate-recovery
#
# The script is installed into a private LIBDIR rather than $(PREFIX)/bin.
# It deliberately has no Python package dependencies beyond the standard
# library so it remains available when the main CineMate environment is broken.
PREFIX  ?= /usr/local
LIBDIR  ?= $(PREFIX)/lib/cinemate-recovery
SYSDDIR ?= /etc/systemd/system

SCRIPT  = cinemate-recovery.py
SERVICE = cinemate-recovery.service

.PHONY: all install enable disable start stop restart status clean uninstall

all:
	@echo "Nothing to build - use 'make install'"

install:
	install -d $(LIBDIR)
	install -m 755 $(SCRIPT)  $(LIBDIR)/$(SCRIPT)
	install -m 644 $(SERVICE) $(SYSDDIR)/$(SERVICE)
	install -d -m 755 /var/lib/cinemate
	install -d -m 700 /var/lib/cinemate/backups
	systemctl daemon-reload

enable: install
	systemctl enable  $(SERVICE)
	systemctl start   $(SERVICE)

disable:
	- systemctl stop    $(SERVICE)
	- systemctl disable $(SERVICE)

start:
	systemctl start $(SERVICE)

stop:
	systemctl stop $(SERVICE)

restart:
	systemctl restart $(SERVICE)

status:
	systemctl status $(SERVICE)

clean: disable
	- rm -rf $(LIBDIR)
	- rm -f $(SYSDDIR)/$(SERVICE)
	systemctl daemon-reload
	@echo "Removed $(SERVICE) (kept /var/lib/cinemate and its backups)"

uninstall: clean     # alias for convenience
