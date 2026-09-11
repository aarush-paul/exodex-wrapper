"""
Exoplanet data via NASA's Exoplanet Archive TAP service (real, live,
public — https://exoplanetarchive.ipac.caltech.edu/TAP/sync). No API key
needed.

Habitability scoring uses the Earth Similarity Index (ESI), a real,
published method (Schulze-Makuch et al. 2011) — not a custom formula,
since the original project's exact methodology wasn't recoverable. ESI
combines radius, density, escape velocity, and equilibrium temperature
into a 0-1 score via weighted geometric means, each normalized against
Earth's own values. Swapping in a different formula later just means
replacing `compute_esi()` — nothing else downstream needs to change.
"""

import csv
from pathlib import Path
from typing import Optional

import requests

TAP_BASE = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

EARTH_MEAN_SURFACE_TEMP_K = 288.0

FEATURED_SYSTEMS = [
    "TRAPPIST-1", "Kepler-186", "Kepler-442", "Proxima Cen",
    "TOI-700", "Kepler-62", "HD 40307", "GJ 667 C",
]

ARCHIVE_PATH = Path(__file__).resolve().parent.parent / "main_data.csv"
_ARCHIVE_SYSTEMS: Optional[dict[str, dict]] = None


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _archive_planet(row: dict, star: dict) -> dict:
    a_au = _number(row.get("pl_orbsmax"))
    period_days = _number(row.get("pl_orbper"))
    if a_au is None and period_days and star["mass_solar"]:
        a_au = (star["mass_solar"] * (period_days / 365.25) ** 2) ** (1 / 3)
    if period_days is None and a_au and star["mass_solar"]:
        period_days = 365.25 * (a_au ** 3 / star["mass_solar"]) ** 0.5
    radius_earth = _number(row.get("pl_rade"))
    mass_earth = _number(row.get("pl_bmasse"))
    eq_temp = _number(row.get("pl_eqt"))
    estimated = False
    if eq_temp is None:
        eq_temp = estimate_eq_temp_k(star["teff_k"], star["radius_solar"], a_au)
        estimated = eq_temp is not None
    return {
        "name": row.get("pl_name"),
        "a_au": a_au,
        "e": _number(row.get("pl_orbeccen")) or 0.0,
        "i_deg": _number(row.get("pl_orbincl")),
        "period_days": period_days,
        "radius_earth": radius_earth,
        "mass_earth": mass_earth,
        "eq_temp_k": eq_temp,
        "eq_temp_estimated": estimated,
        "esi": compute_esi(radius_earth, mass_earth, eq_temp),
        "planet_type": classify_planet_type(radius_earth, mass_earth),
    }


def _load_archive() -> dict[str, dict]:
    """Load the bundled NASA archive once, retaining its canonical rows."""
    global _ARCHIVE_SYSTEMS
    if _ARCHIVE_SYSTEMS is not None:
        return _ARCHIVE_SYSTEMS
    systems = {}
    with ARCHIVE_PATH.open(newline="", encoding="utf-8") as handle:
        rows = (line for line in handle if not line.startswith("#") and line.strip())
        for row in csv.DictReader(rows):
            if row.get("default_flag") != "1" or not row.get("hostname"):
                continue
            hostname = row["hostname"]
            system = systems.setdefault(hostname, {
                "hostname": hostname,
                "star": {
                    "teff_k": _number(row.get("st_teff")),
                    "radius_solar": _number(row.get("st_rad")),
                    "mass_solar": _number(row.get("st_mass")),
                    "spectral_type": row.get("st_spectype") or None,
                    "distance_pc": _number(row.get("sy_dist")),
                },
                "planets": [],
            })
            planet = _archive_planet(row, system["star"])
            if planet["name"]:
                system["planets"].append(planet)

    for system in systems.values():
        system["planets"].sort(key=lambda planet: planet["a_au"] if planet["a_au"] is not None else float("inf"))
        system["habitable_zone_au"] = habitable_zone_au(
            system["star"]["teff_k"], system["star"]["radius_solar"]
        )
        for planet in system["planets"]:
            a_au = planet["a_au"]
            planet["in_habitable_zone"] = (
                None if system["habitable_zone_au"] is None or a_au is None else
                system["habitable_zone_au"]["inner_au"] <= a_au <= system["habitable_zone_au"]["outer_au"]
            )
    _ARCHIVE_SYSTEMS = systems
    return systems


def _tap_query(adql: str, fmt: str = "json") -> list:
    resp = requests.get(
        TAP_BASE, params={"query": adql, "format": fmt}, timeout=20,
        headers={"User-Agent": "ssa-dashboard/1.0 (https://github.com/; personal project)"},
    )
    resp.raise_for_status()
    return resp.json()


def search_hostnames(q: str, limit: int = 15) -> list:
    """Distinct star (host) names matching a search substring."""
    q_escaped = q.replace("'", "''")
    adql = (
        f"select distinct hostname from ps "
        f"where hostname like '%{q_escaped}%' "
        f"order by hostname asc"
    )
    rows = _tap_query(adql)
    return [r["hostname"] for r in rows[:limit]]


def esi_component(x: float, x_ref: float, weight: float) -> float:
    return (1 - abs((x - x_ref) / (x + x_ref))) ** weight


def compute_esi(radius_earth: Optional[float], mass_earth: Optional[float], eq_temp_k: Optional[float]) -> Optional[float]:
    if not radius_earth or not mass_earth or radius_earth <= 0 or mass_earth <= 0:
        return None

    density_rel = mass_earth / (radius_earth ** 3)          # relative to Earth = 1
    esc_vel_rel = (mass_earth / radius_earth) ** 0.5          # relative to Earth = 1

    esi_radius = esi_component(radius_earth, 1.0, 0.57)
    esi_density = esi_component(density_rel, 1.0, 1.07)
    esi_interior = (esi_radius * esi_density) ** 0.5

    esi_escvel = esi_component(esc_vel_rel, 1.0, 0.70)
    if eq_temp_k and eq_temp_k > 0:
        esi_temp = esi_component(eq_temp_k, EARTH_MEAN_SURFACE_TEMP_K, 5.58)
        esi_surface = (esi_escvel * esi_temp) ** 0.5
    else:
        esi_surface = esi_escvel  # no temperature data , degrade gracefully rather than failing

    return round((esi_interior * esi_surface) ** 0.5, 3)


def habitable_zone_au(st_teff: Optional[float], st_rad: Optional[float]) -> Optional[dict]:
    """
    Conservative habitable zone bounds in AU, from a standard simplified
    formula: stellar luminosity relative to the Sun via L = R^2 * (T/T_sun)^4,
    then inner/outer HZ edges via L^0.5 scaled by empirical solar-flux
    boundaries. This is the textbook simplified version, not a full
    Kopparapu et al. climate-model calculation — good for a visualization,
    not a research claim.
    """
    if not st_teff or not st_rad or st_teff <= 0 or st_rad <= 0:
        return None
    T_sun = 5772.0
    luminosity = (st_rad ** 2) * ((st_teff / T_sun) ** 4)
    inner_au = (luminosity / 1.1) ** 0.5
    outer_au = (luminosity / 0.53) ** 0.5
    return {"inner_au": round(inner_au, 4), "outer_au": round(outer_au, 4)}


def classify_planet_type(radius_earth: Optional[float], mass_earth: Optional[float]) -> str:
    """
    NASA's own public exoplanet catalog (science.nasa.gov/exoplanets/exoplanet-catalog)
    sorts every confirmed planet into one of these four categories — this
    reproduces that same scheme (standard radius thresholds used across
    NASA's popular-science exoplanet materials), falling back to a rough
    mass-based estimate when radius isn't measured.
    """
    if radius_earth:
        if radius_earth < 1.25:
            return "Terrestrial"
        if radius_earth < 2.0:
            return "Super Earth"
        if radius_earth < 6.0:
            return "Neptune-like"
        return "Gas Giant"
    if mass_earth:
        if mass_earth < 2:
            return "Terrestrial"
        if mass_earth < 10:
            return "Super Earth"
        if mass_earth < 50:
            return "Neptune-like"
        return "Gas Giant"
    return "Unknown"


def estimate_eq_temp_k(star_teff: Optional[float], star_radius_solar: Optional[float], a_au: Optional[float]) -> Optional[float]:
    """
    Zero-albedo equilibrium temperature estimate: T = T_star * sqrt(R_star / (2a)),
    a standard, real formula — used only when the Archive's own directly-measured
    pl_eqt is missing (common; many planets, especially radial-velocity detections,
    don't have a reported equilibrium temperature). Verified against Earth before
    shipping: T_sun=5772K, R_sun=1, a=1AU gives ~278K, matching the textbook
    zero-albedo estimate for Earth.
    """
    if not star_teff or not star_radius_solar or not a_au or a_au <= 0:
        return None
    SOLAR_RADIUS_IN_AU = 1 / 215.032
    r_star_au = star_radius_solar * SOLAR_RADIUS_IN_AU
    return star_teff * (r_star_au / (2 * a_au)) ** 0.5


def get_system(hostname: str) -> dict:
    archive = _load_archive()
    if hostname in archive:
        return {**archive[hostname], "found": True}

    hostname_escaped = hostname.replace("'", "''")
    cols = (
        "pl_name,pl_orbsmax,pl_orbeccen,pl_orbincl,pl_orbper,"
        "pl_rade,pl_bmasse,pl_eqt,"
        "st_teff,st_rad,st_mass,st_spectype,sy_dist"
    )
    adql = (
        f"select {cols} from ps "
        f"where default_flag=1 and hostname='{hostname_escaped}' "
        f"order by pl_orbsmax asc"
    )
    rows = _tap_query(adql)
    if not rows:
        return {"hostname": hostname, "found": False, "planets": [], "star": None}

    first = rows[0]
    star = {
        "teff_k": first.get("st_teff"),
        "radius_solar": first.get("st_rad"),
        "mass_solar": first.get("st_mass"),
        "spectral_type": first.get("st_spectype"),
        "distance_pc": first.get("sy_dist"),
    }
    hz = habitable_zone_au(star["teff_k"], star["radius_solar"])

    planets = []
    for r in rows:
        a_au = r.get("pl_orbsmax")
        period_days = r.get("pl_orbper")
        # Some planets (esp. radial-velocity detections) are missing semi-major
        # axis but have period + we have stellar mass — recover it via Kepler's
        # third law (a^3 = M_star * P_years^2, standard units AU/solar-mass/year)
        if a_au is None and period_days and star["mass_solar"]:
            period_years = period_days / 365.25
            a_au = (star["mass_solar"] * period_years ** 2) ** (1/3)

        radius_earth = r.get("pl_rade")
        mass_earth = r.get("pl_bmasse")
        eq_temp = r.get("pl_eqt")
        eq_temp_estimated = False
        if eq_temp is None:
            eq_temp = estimate_eq_temp_k(star["teff_k"], star["radius_solar"], a_au)
            eq_temp_estimated = eq_temp is not None
        esi = compute_esi(radius_earth, mass_earth, eq_temp)
        planet_type = classify_planet_type(radius_earth, mass_earth)

        in_hz = None
        if hz and a_au is not None:
            in_hz = hz["inner_au"] <= a_au <= hz["outer_au"]

        planets.append({
            "name": r.get("pl_name"),
            "a_au": a_au,
            "e": r.get("pl_orbeccen") or 0.0,
            "i_deg": r.get("pl_orbincl"),
            "period_days": period_days,
            "radius_earth": radius_earth,
            "mass_earth": mass_earth,
            "eq_temp_k": eq_temp,
            "eq_temp_estimated": eq_temp_estimated,
            "esi": esi,
            "in_habitable_zone": in_hz,
            "planet_type": planet_type,
        })

    return {
        "hostname": hostname,
        "found": True,
        "star": star,
        "habitable_zone_au": hz,
        "planets": planets,
    }


def catalog_systems(query: str = "", limit: int = 100) -> list[dict]:
    needle = query.casefold().strip()
    matches = [
        system for system in _load_archive().values()
        if needle in system["hostname"].casefold()
    ]
    matches.sort(key=lambda system: system["hostname"].casefold())
    return [
        {
            "hostname": system["hostname"],
            "planet_count": len(system["planets"]),
            "distance_pc": system["star"]["distance_pc"],
        }
        for system in matches[:limit]
    ]


def archive_stats() -> dict:
    systems = _load_archive()
    return {
        "systems": len(systems),
        "planets": sum(len(system["planets"]) for system in systems.values()),
        "source": ARCHIVE_PATH.name,
    }
