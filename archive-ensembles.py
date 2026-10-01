#!/usr/bin/env python3
"""
Archive les membres d'ensemble météo d'Open-Meteo (un fichier Parquet par run de modèle).

À lancer toutes les 3 h (cron, systemd timer ou GitHub Actions). Le script lit l'heure
d'initialisation du dernier run de chaque modèle et ne télécharge que les runs pas encore
archivés : on peut donc le lancer aussi souvent qu'on veut sans créer de doublons.

Sortie : archive/<modèle>/<année>/<modèle>_<AAAAMMJJ>T<HH>Z.parquet
Colonnes : run_time, valid_time, lead_h, member, puis une colonne par variable.
member 0 = run de contrôle, 1..N-1 = membres perturbés.

Dépendances : pip install requests pandas pyarrow
"""
from __future__ import annotations

import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

# ----------------------------------------------------------------------------- config
LAT, LON = 50.63, 3.06          # à remplacer par les coordonnées de la maison
try:
    ARCHIVE_DIR = Path(__file__).resolve().parent / "archive"   # à côté du script
except NameError:   # certains éditeurs (EduPython, PyScripter, Jupyter...) ne définissent pas __file__
    ARCHIVE_DIR = Path.cwd() / "archive"

# nom du modèle dans l'API -> (domaine pour meta.json, horizon gardé en jours)
MODELS = {
    # Modèle principal : toutes les variables, vent à 100 m, 7 jours et plus (runs 00Z/12Z ;
    # les runs 06Z/18Z s'arrêtent à 6 jours).
    "ecmwf_ifs025": ("ecmwf_ifs025_ensemble", 10),  # 51 membres, run toutes les 6 h, 25 km
    # Complément plus fin sur 5 jours ; pas d'humidité, d'ET0 ni de vent à 100 m (80 m à la place).
    "icon_eu":      ("dwd_icon_eu_eps", 5),         # 40 membres, run toutes les 6 h, ~13 km
    # "ecmwf_aifs025": ("ecmwf_aifs025_ensemble", 10),  # 51 membres, pas de rafales
    # "gfs025":     ("ncep_gefs025", 10),           # 31 membres, vent à 10 m seulement
}

# Les variables qu'un modèle ne fournit pas restent dans le fichier, vides (NaN) :
# tous les fichiers ont ainsi les mêmes colonnes. 16 variables = 1,6 appel par requête.
VARIABLES = [
    # air : densité de l'air (éolien), température des panneaux, chauffage
    "temperature_2m", "relative_humidity_2m", "surface_pressure", "cloud_cover",
    # soleil (PVLib) : GHI, DNI, DHI en W/m², moyenne sur l'heure PRÉCÉDENTE
    "shortwave_radiation", "direct_normal_irradiance", "diffuse_radiation",
    # vent (m/s, degrés) : vent au moyeu par la loi de Hellmann entre 10 m et 80/100 m
    "wind_speed_10m", "wind_speed_80m", "wind_speed_100m",
    "wind_direction_10m", "wind_direction_80m", "wind_direction_100m", "wind_gusts_10m",
    # eau : pluie récupérée (mm, cumul sur l'heure précédente), besoin d'arrosage (mm)
    "precipitation", "et0_fao_evapotranspiration",
]

KEEP_RUN_HOURS: set[int] | None = None   # ex. {0, 12} pour ne garder que 00Z et 12Z

BASE = "https://ensemble-api.open-meteo.com"
# ------------------------------------------------------------------------------------

log = logging.getLogger("archive")
MEMBER_KEY = re.compile(r"^(?P<var>.+?)(?:_member(?P<m>\d+))?$")


def get_json(url: str, params: dict | None = None, tries: int = 3) -> dict:
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=60)
            data = r.json()
            if r.status_code == 200 and not data.get("error"):
                return data
            raise RuntimeError(data.get("reason", f"HTTP {r.status_code}"))
        except Exception as e:  # réseau, JSON invalide, erreur API
            if i == tries - 1:
                raise
            log.warning("%s -> %s, nouvel essai dans %ds", url, e, 10 * (i + 1))
            time.sleep(10 * (i + 1))


def last_run(domain: str) -> tuple[datetime, datetime]:
    """(heure d'initialisation du dernier run, dernière échéance native de ce run)."""
    meta = get_json(f"{BASE}/data/{domain}/static/meta.json")
    utc = lambda s: datetime.fromtimestamp(s, tz=timezone.utc)
    # data_end_time est exclusif : la dernière échéance est un pas de temps natif avant.
    return (utc(meta["last_run_initialisation_time"]),
            utc(meta["data_end_time"] - meta["temporal_resolution_seconds"]))


def to_frame(data: dict, run: datetime, run_end: datetime, horizon_days: int) -> pd.DataFrame:
    hourly = dict(data["hourly"])
    times = pd.to_datetime(hourly.pop("time"), utc=True)

    by_member: dict[int, dict[str, list]] = {}
    for key, values in hourly.items():
        m = MEMBER_KEY.match(key)
        by_member.setdefault(int(m["m"] or 0), {})[m["var"]] = values

    frames = []
    for member, cols in sorted(by_member.items()):
        f = pd.DataFrame(cols, index=times)
        f.insert(0, "member", member)
        frames.append(f)
    df = pd.concat(frames).rename_axis("valid_time").reset_index()

    variables = list(VARIABLES)
    df = df.reindex(columns=["valid_time", "member", *variables])   # mêmes colonnes partout
    df[variables] = df[variables].astype("float32")

    df.insert(0, "run_time", pd.Timestamp(run))
    df.insert(2, "lead_h", ((df["valid_time"] - df["run_time"]).dt.total_seconds() // 3600).astype("int16"))
    # L'API recolle des runs précédents avant run_time ET après la fin de ce run (ex. ECMWF 18Z
    # ne va qu'à 144 h, la suite vient du run 12Z) : on ne garde que la prévision de CE run.
    df = df[(df["lead_h"] >= 0) & (df["lead_h"] <= horizon_days * 24)
            & (df["valid_time"] <= pd.Timestamp(run_end))]
    df = df.dropna(subset=variables, how="all")              # au-delà de l'horizon du modèle
    df["member"] = df["member"].astype("int8")
    return df.sort_values(["member", "valid_time"]).reset_index(drop=True)


def archive_model(model: str, domain: str, horizon_days: int) -> str:
    run, run_end = last_run(domain)
    if KEEP_RUN_HOURS is not None and run.hour not in KEEP_RUN_HOURS:
        return f"{model}: run {run:%Y-%m-%d %HZ} ignoré (KEEP_RUN_HOURS)"

    out = ARCHIVE_DIR / model / f"{run:%Y}" / f"{model}_{run:%Y%m%dT%H}Z.parquet"
    if out.exists():
        return f"{model}: run {run:%Y-%m-%d %HZ} déjà archivé"

    data = get_json(f"{BASE}/v1/ensemble", {
        "latitude": LAT, "longitude": LON, "models": model,
        "hourly": ",".join(VARIABLES),
        # L'API démarre à 00:00 du jour courant : past_days=1 couvre les runs de la veille
        # (ex. ECMWF 18Z, publié le lendemain matin), forecast_days couvre tout l'horizon.
        "past_days": 1, "forecast_days": horizon_days + 1,
        "timezone": "GMT", "wind_speed_unit": "ms",
    })

    # Si un nouveau run est sorti pendant le téléchargement, on ne sait pas lequel on a reçu :
    # on abandonne, le prochain passage le récupérera.
    if last_run(domain) != (run, run_end):
        return f"{model}: nouveau run publié pendant le téléchargement, réessai au prochain passage"

    df = to_frame(data, run, run_end, horizon_days)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    df.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(out)                          # écriture atomique : jamais de fichier à moitié écrit
    return (f"{model}: run {run:%Y-%m-%d %HZ} archivé -> {out.relative_to(ARCHIVE_DIR)} "
            f"({df['member'].nunique()} membres, {df['lead_h'].max()} h, "
            f"{int(df[VARIABLES].notna().any().sum())}/{len(VARIABLES)} variables remplies, "
            f"{out.stat().st_size / 1024:.0f} Ko)")


def main() -> int:
    # Journal propre au script : fonctionne aussi dans les éditeurs (Pyzo...) qui ont déjà
    # configuré le logging et ignorent logging.basicConfig().
    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    log.info("Dossier d'archive : %s", ARCHIVE_DIR)
    failed = 0
    for model, (domain, horizon) in MODELS.items():
        try:
            log.info(archive_model(model, domain, horizon))
        except Exception:
            failed += 1
            log.exception("%s: échec", model)
    return 1 if failed else 0


if __name__ == "__main__":
    if main():          # code de sortie 1 seulement en cas d'échec (pour GitHub Actions) ;
        sys.exit(1)     # en cas de succès, pas de SystemExit qui affolerait l'éditeur