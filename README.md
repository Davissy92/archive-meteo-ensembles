# archive-meteo-ensembles
Archivage des membres d'ensemble météo depuis 3 modèles sur l'API d'Open-Meteo

Modèle d'ensemble : trois modèles, archivés chacun dans son fichier : ECMWF IFS 0,25° (51 membres, 15 jours, pas de 3 h), ECMWF AIFS 0,25° (le modèle d'IA de l'ECMWF : 51 membres, 15 jours, pas de 6 h) et DWD ICON-EU-EPS (40 membres, 5 jours, pas horaire, maille de 13 km).

Variables en sortie :

| Donnée | Unité | Sert à | ECMWF IFS | ECMWF AIFS | ICON-EU |
| :---- | :---- | :---- | :---- | :---- | :---- |
| Température à 2 m | °C | panneaux, densité de l'air, consommation | ✓ | ✓ | ✓ |
| Humidité relative | % | densité de l'air | ✓ | ✓ | — |
| Pression au sol | hPa | densité de l'air | ✓ | ✓ | ✓ |
| Couverture nuageuse | % | variable d'appoint (solaire, consommation) | ✓ | ✓ | ✓ |
| Rayonnement global (GHI) | W/m² | PVLib | ✓ | ✓ | ✓ |
| Rayonnement direct normal (DNI) | W/m² | PVLib | ✓ | ✓ | ✓ |
| Rayonnement diffus (DHI) | W/m² | PVLib | ✓ | ✓ | ✓ |
| Vent à 10 m | m/s | éolien, température des panneaux | ✓ | ✓ | ✓ |
| Vent à 80 m | m/s | vent au moyeu (Hellmann) | — | — | ✓ |
| Vent à 100 m | m/s | vent au moyeu (Hellmann) | ✓ | ✓ | — |
| Direction du vent à 10 m | ° | éolien (sin/cos) | ✓ | ✓ | ✓ |
| Direction à 80 m / à 100 m | ° | éolien | 100 m | 100 m | 80 m |
| Rafales à 10 m | m/s | éolien | ✓ | — | ✓ |
| Précipitations | mm | pluie récupérée (brique 4\) | ✓ | ✓ | ✓ |
| Évapotranspiration ET0 | mm | besoin d'arrosage (brique 6\) | ✓ | ✓ | — |
