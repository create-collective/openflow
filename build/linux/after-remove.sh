#!/bin/bash
#
# OpenFlow .deb post-remove. As with after-install.sh, setting deb.afterRemove replaces
# electron-builder's script, so its default (app-builder-lib 26.15.3,
# templates/linux/after-remove.tpl) is carried verbatim first. Shell variables are $NAME, never
# dollar-brace: electron-builder expands those as macros and fails on unknown names.
#
# ---- electron-builder default: begin ----
# Delete the link to the binary
# update-alternatives --remove <name> <path>: 'path' must be the registered alternative binary,
# not the generic symlink — see https://man7.org/linux/man-pages/man1/update-alternatives.1.html
if type update-alternatives >/dev/null 2>&1; then
    update-alternatives --remove '${executable}' '/opt/${sanitizedProductName}/${executable}'
else
    rm -f '/usr/bin/${executable}'
fi

APPARMOR_PROFILE_DEST='/etc/apparmor.d/${executable}'

# Remove and unload apparmor profile.
if [ -f "$APPARMOR_PROFILE_DEST" ]; then
  # Unload the profile from the running kernel before deleting the file so the
  # policy is not left enforced until the next reboot.  Mirror the chroot guard
  # used in the after-install script — live AppArmor operations are not
  # meaningful inside a chroot.
  # https://wiki.debian.org/AppArmor/HowToUse
  if apparmor_status --enabled > /dev/null 2>&1; then
    if ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; } && hash apparmor_parser 2>/dev/null; then
      apparmor_parser --remove "$APPARMOR_PROFILE_DEST" || true
    fi
  fi
  rm -f "$APPARMOR_PROFILE_DEST"
fi
# ---- electron-builder default: end ----

# ---- OpenFlow: the keyboard's serial ports ----
# dpkg has already deleted /usr/lib/udev/rules.d/70-openflow.rules by the time this runs (it is
# a packaged file). Reload so udev forgets it; the ACL it granted goes at the next replug.
# This also runs on upgrade, when the new package has just put the file back; reloading is
# harmless then.
if command -v udevadm >/dev/null 2>&1; then
    udevadm control --reload-rules >/dev/null 2>&1 || true
fi
