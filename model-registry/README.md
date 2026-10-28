# Model registry

Container **Model registry**: MLflow tracking server met modelversies, trainingsruns en testscores. Artefacten staan op een lokaal volume.

- de training pipeline logt runs en registreert nieuwe modelversies;
- de forecast pipeline laadt alleen de versie met alias `production`.

Bevat straks alleen een `Dockerfile` voor de MLflow-server.
