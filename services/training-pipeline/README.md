# Ingest and training pipeline

Container **Ingest and training pipeline** (Python, PyCaret, scikit-learn, XGBoost): draait na elke import.

1. `training_orchestrator.py`: ontvangt de trigger (`POST /training-runs`);
2. `effect_measurement.py`: vergelijkt werkelijk verbruik met de P50-voorspelling om te meten of adviezen zijn opgevolgd;
3. `feature_builder.py`: bouwt de trainingsset (geen lags van gisteren);
4. `model_selector.py`: PyCaret vergelijkt veel algoritmes en kiest het beste;
5. `model_trainer.py`: traint het gekozen algoritme als quantile-modellen (P10, P50, P90);
6. `model_evaluator.py`: zet een nieuw model alleen in de model registry live als het beter scoort.

Verkennend onderzoek staat in `notebooks/`.
