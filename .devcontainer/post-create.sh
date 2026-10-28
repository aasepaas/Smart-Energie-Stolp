#!/usr/bin/env bash
# Draait eenmalig na het bouwen van de werkcontainer.
# Installeert alleen wat al bestaat, zodat het script blijft werken terwijl de repo groeit.
set -euo pipefail

python -m pip install --upgrade pip

if [ -f packages/ses-common/pyproject.toml ]; then
  pip install -e packages/ses-common
fi

for service in services/*/; do
  if [ -f "${service}pyproject.toml" ]; then
    pip install -e "${service}"
  fi
done

if [ -f web-app/package.json ]; then
  (cd web-app && npm install)
fi
