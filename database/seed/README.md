# Seed

Invented data for development, tests and the demo, in the same format as the real export. Never put real meter data here.

| File | Content |
| --- | --- |
| `meter_data_4_weeks.csv` | Meter data export: 20 participants, 21 meters, 16 March to 13 April 2026 (local time, includes the switch to summer time), 52,328 rows |
| `participants.csv` | Link table participant -> meter with validity period and profile (solar panels, EV, heat pump) |
| `test_seed_data.py` | Checks that the files import without errors and behave like a community |

## The community

19 households (small consumer connections `KV`) and a sports club (large consumer connection `GV01`). 10 households and the sports club have solar panels (south, east or west), 5 households have an EV, and 6 households and the sports club have a heat pump. The weather is the same for everyone: clear, mixed or overcast days.

Feed-in and consumption are calculated in steps of 5 minutes and summed per quarter hour, so both can be > 0 in the same quarter. Over the 4 weeks the simultaneity is about 31%; calculated per day it would wrongly look like almost 100%.

Built-in situations for the import:

- **Meter switch:** P07 gets a new meter on 1 April (`KV07` ends, `KV21` starts).
- **Participant joins later:** P18 (`KV18`) starts on 30 March.
- **Outage:** `KV04` misses 3 hours on 8 April (12 quarters, a gap).

## Usage

```bash
python -m pytest database/seed                                       # check the seed data

cd services/data-processing-service
python -m data_processing_service ../../database/seed/meter_data_4_weeks.csv   # import into the dev database
```
