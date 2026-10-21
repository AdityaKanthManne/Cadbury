#!/bin/bash
# Double-click in Finder to install or update Desktop Butler from this folder.
cd "$(dirname "$0")"
bash scripts/setup_mac.sh --yes
status=$?
echo
if [[ $status -eq 0 ]]; then
  echo "Done. You can close this window."
else
  echo "Setup stopped with an error (see above). Copy the last lines for help."
fi
