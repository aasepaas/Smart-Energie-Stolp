# Data processing service

Container **Data processing service** (Python, Flask, pandas): importeert meterdata en berekent de gelijktijdigheid.

Stappen per import:

1. `import_endpoint.py`: ontvangt de CSV (`POST /imports`), legt bestandsnaam, hash en periode vast;
2. `import_orchestrator.py`: voert de stappen in volgorde uit;
3. `csv_parser.py`: komma als scheidings- en decimaalteken, tijdstempel naar UTC;
4. `validator.py`: dubbelen, gaten (niet als 0) en grenzen per meter;
5. `meter_linker.py`: meter-id naar deelnemer via de koppeltabel;
6. `simultaneity_calculator.py`: gedeeld = min(teruglevering, afname) per kwartier, naar rato verdeeld;
7. `training_notifier.py`: start de training pipeline.

De import is idempotent: exports mogen elkaar overlappen.
