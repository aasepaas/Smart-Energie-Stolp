"""Instellingen van de Data processing service."""

# Maximale energie per kwartier per metertype (kWh), alleen voor waarschuwingen.
# KV: grootste kleinverbruikaansluiting 3x80A  -> ~55 kW  -> ~13,8 kWh per kwartier
# GV: grootste aansluiting in de Stolp 250A (C4) -> ~173 kW -> ~43,3 kWh per kwartier
# Later per meter te overschrijven via de tabel settings (sleutel "meter_limits").
DEFAULT_LIMITS_KWH: dict[str, float] = {"KV": 13.8, "GV": 43.3}
FALLBACK_LIMIT_KWH = DEFAULT_LIMITS_KWH["GV"]

# De Backend API accepteert maximaal 10.000 rijen per schrijfverzoek.
MAX_BATCH = 10_000

# Seconden per verzoek naar de Backend API (een batch van 10.000 rijen kan even duren).
BACKEND_TIMEOUT = 120

# Recalculate simultaneity in chunks of one week: 7 x 96 = 672 quarters per
# PUT /simultaneity (below MAX_BATCH) and a limited number of readings per GET /readings.
SIMULTANEITY_CHUNK_DAYS = 7
