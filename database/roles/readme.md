# Rollen en rechten: Smart Energie Stolp

Dit document beschrijft welke rollen er in Smart Energie Stolp (SES) zijn en welke rechten zij hebben op de database (PostgreSQL met TimescaleDB).

Er zijn **twee soorten rollen**:

1. **Applicatierollen**: voor mensen die inloggen op de web app. De rol staat in `users.role` en in het JWT, en wordt gecontroleerd in de web app (route guards) en de Frontend API.
2. **Databaserollen**: waarmee de services bij de database komen. De rechten worden in PostgreSQL afgedwongen met `GRANT` en row-level security (RLS).

Elke applicatierol en elke service hoort bij precies één databaserol.

## Overzicht

| Persoon of service | Applicatierol | Databaserol |
|---|---|---|
| Deelnemer | `participant` | `web_participant` (inzien en beheren eigen data) |
| Opdrachtgever, begeleiders | `viewer` | `web_participant` (zonder gekoppelde deelnemer) |
| Beheerder | `administrator` | `web_admin` (inzien en beheren data van alle deelnemers en systeeminstellingen) |
| Technisch beheer | `superadmin` | `web_admin` (beheert de omgeving zelf, zoals rollen en rechten van accounts) |
| Data processing service | – | `svc_processing` |
| Ingest and training pipeline | – | `svc_training` |
| Forecast pipeline | – | `svc_forecast` |
| Databasebeheerder | – | `ses_dba` (beheert alles omtrent de database) |

## 1. Applicatierollen

| Recht | participant | viewer | administrator | superadmin |
|---|:-:|:-:|:-:|:-:|
| Inloggen | ✓ | ✓ | ✓ | ✓ |
| Dynamische prijzen bekijken | ✓ | ✓ | ✓ | ✓ |
| Gelijktijdigheid gemeenschap bekijken | ✓ | ✓ | ✓ | ✓ |
| Eigen verbruik, opwek en voorspellingen bekijken | ✓ | – | – | – |
| Eigen advies bekijken en feedback geven | ✓ | – | – | – |
| Eigen comfortgrenzen aanpassen | ✓ | – | – | – |
| Data van alle deelnemers bekijken | – | – | ✓ | ✓ |
| Meterdata uploaden (CSV) | – | – | ✓ | ✓ |
| Meters aan deelnemers koppelen | – | – | ✓ | ✓ |
| Deelnemers en hun apparaten beheren | – | – | ✓ | ✓ |
| Instellingen beheren | – | – | ✓ | ✓ |
| Deelnemer-accounts beheren | – | – | ✓ | ✓ |
| Admin-accounts beheren | – | – | – | ✓ |

Het verschil tussen `administrator` en `superadmin` wordt in de Frontend API gecontroleerd; in de database gebruiken ze dezelfde rol (`web_admin`).

## 2. Databaserollen

**Legenda:** R = lezen · I = toevoegen · W = wijzigen · D = verwijderen · *eigen* = alleen rijen van de ingelogde deelnemer (RLS)

| Tabel | web_participant | web_admin | svc_processing | svc_training | svc_forecast |
|---|---|---|---|---|---|
| `participants` | R *eigen* | R I W D | – | R | R |
| `users` | R *eigen* ¹ | R I W D ¹ | – | – | – |
| `participant_appliances` | R W *eigen* ⁵ | R I W D | – | – | R |
| `settings` | – | R I W | R | R | R |
| `import_log` | – | R I W | R I W | – | – |
| `meters` | R *eigen* | R W ² | R I | R | R |
| `readings` | R *eigen* | R | R I W | R | R |
| `community_simultaneity` | R | R | R I W D | R | R |
| `forecasts` | R *eigen* | R | – | R | R I |
| `energy_prices` | R | R | – | – | R I W |
| `advice` | R *eigen*, W ³ | R | – | R W ⁴ | R I W D ⁶ |

1. Nooit de kolom `password_hash`; inloggen gaat via een aparte databasefunctie (`SECURITY DEFINER`).
2. Alleen de kolom `participant_id` (meter koppelen aan een deelnemer).
3. Alleen de kolom `feedback`.
4. Alleen de kolom `measured_effect_kwh`.
5. Alleen de comfortgrenzen (`power_kw`, `earliest_start`, `latest_end`, `min_run_minutes`), niet aan welke deelnemer het apparaat hoort.
6. W alleen op de adviesvelden, niet op `feedback` en `measured_effect_kwh`. Zo kan de avondrun opnieuw draaien zonder de reactie van de deelnemer of het gemeten effect te overschrijven.

De `viewer` gebruikt `web_participant` zonder gekoppelde deelnemer. Alle tabellen met *eigen* geven dan geen rijen terug; alleen `community_simultaneity` en `energy_prices` zijn zichtbaar.

## 3. Technische rollen

| Rol | Inloggen | Doel |
|---|:-:|---|
| `ses_frontend` | ✓ | Inlogrol van de Frontend API; wisselt per verzoek naar `web_participant` of `web_admin` |
| `ses_backend` | ✓ | Inlogrol van de Backend API; wisselt per verzoek naar `svc_processing`, `svc_training` of `svc_forecast` |
| `ses_dba` | ✓ | Databasebeheerder; werkt als eigenaar van alle tabellen en beheert de SES-rollen |
| `ses_owner` | – | Eigenaar van alle tabellen, alleen voor migraties |
| `ses_backup` | ✓ | Alleen lezen (lid van `pg_read_all_data`), voor back-ups met `pg_dump` |

Het model registry (MLflow) heeft een eigen opslag en valt buiten deze rollen.

## 4. Installatie

De rollen worden aangemaakt met `rollen_en_rechten.sql`, nadat de tabellen bestaan:

```bash
psql -v ON_ERROR_STOP=1 -f rollen_en_rechten.sql
```

Alle inlogrollen krijgen tijdelijk het wachtwoord `user`. Wijzig ze direct daarna:

```sql
ALTER ROLE ses_dba      PASSWORD '<nieuw wachtwoord>';
ALTER ROLE ses_frontend PASSWORD '<nieuw wachtwoord>';
ALTER ROLE ses_backend  PASSWORD '<nieuw wachtwoord>';
ALTER ROLE ses_backup   PASSWORD '<nieuw wachtwoord>';
```

Zet de echte wachtwoorden in het `.env`-bestand op de server, niet in Git.
