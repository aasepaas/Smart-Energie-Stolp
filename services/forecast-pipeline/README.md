# Forecast pipeline

Container **Forecast pipeline** (Python, scikit-learn, XGBoost, PuLP): draait elke avond om 20:00, nadat de Apex-prijzen voor morgen bekend zijn.

- `scheduler.py`: start de run en roept de stappen aan;
- `price_client.py`: haalt dynamische day-ahead prijzen op (Apex data API);
- `weather_client.py`: haalt de weersverwachting voor 48 uur op;
- `model_loader.py`: laadt de productieversie van de modellen uit MLflow;
- `forecaster.py`: voorspelt opwek en verbruik per kwartier (P10, P50, P90);
- `optimizer.py`: plant flexibele apparaten (vervoer, warmtepomp, airco) in het overschot (MILP met HiGHS);
- `ranker.py`: kiest per deelnemer de top 3 adviezen (high, medium, low impact).
