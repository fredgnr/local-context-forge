#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

printf '%s\n' "Local Context Forge installer"
printf '%s\n' "This window will stay open if anything needs your attention."
printf '\n'

if "${script_dir}/install.sh"; then
  printf '\n%s\n' "Installation finished. You may close this window."
else
  status=$?
  printf '\n%s\n' "Installation stopped with exit code ${status}."
  printf '%s\n' "Fix the message above, then double-click install.command again."
  read -r -p "Press Return to close..." _
  exit "$status"
fi
