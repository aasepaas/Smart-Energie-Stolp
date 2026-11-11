"""Instellingen uit omgevingsvariabelen, met veilige standaardwaarden voor ontwikkelen."""

from __future__ import annotations

import os
from pathlib import Path

# Maximale energie per kwartier per metertype (kWh), alleen voor waarschuwingen.
# KV: grootste kleinverbruikaansluiting 3x80A  -> ~55 kW  -> ~13,8 kWh per kwartier
# GV: grootste aansluiting in de Stolp 250A (C4) -> ~173 kW -> ~43,3 kWh per kwartier
# Later per meter te overschrijven via de tabel settings (sleutel "meter_limits").
DEFAULT_LIMITS_KWH: dict[str, float] = {"KV": 13.8, "GV": 43.3}
FALLBACK_LIMIT_KWH = DEFAULT_LIMITS_KWH["GV"]

# De Backend API accepteert maximaal 10.000 rijen per schrijfverzoek.
MAX_BATCH = 10_000


def _default_dryrun_dir() -> Path:
    """data/dryrun in de root van de repo (staat in .gitignore), anders ./dryrun-output."""
    for parent in Path(__file__).resolve().parents:
        if (parent / ".devcontainer").is_dir() and (parent / "data").is_dir():
            return parent / "data" / "dryrun"
    return Path.cwd() / "dryrun-output"


# Welke backend de service gebruikt. Nu alleen "dryrun"; "http" volgt zodra de Backend API klaar is.
BACKEND_MODE = os.environ.get("SES_BACKEND_MODE", "dryrun")
DRYRUN_DIR = Path(os.environ.get("SES_DRYRUN_DIR") or _default_dryrun_dir())
