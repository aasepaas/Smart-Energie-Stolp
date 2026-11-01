Ontwerp in C4-model:

Het C4-model staat volledig in deze map:

- `ses_v0.1_en.c4`: het model, niveau 1 tot en met 3
- `likec4.config.json`: maakt van deze map het LikeC4-project "Smart Energie Stolp"
- `.likec4/`: handmatig aangepaste layouts van views (`<view-id>.likec4.snap`)

Ontwerp kan in de terminal gestart worden met de volgende commando (vanuit de root of vanuit deze map):
npx likec4 start

hiervoor is de extension likec4 in Visual Studio Code nodig.

Voor een automatische export van de views, gebruik:

node export-views.mjs

in de architecture folder