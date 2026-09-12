# ExoDex 

A full-stack space situational awareness platform: live satellite tracking, real solar system mechanics, and exoplanet habitability analysis, all in one 3D dashboard.

---

## What it does

### Live Earth Satellite Tracking
- Real-time positions of 20+ satellite categories (Starlink, ISS, GPS, debris fields, etc.) derived from CelesTrak TLE data propagated with SGP4
- Collision/conjunction screening between arbitrary object groups with configurable distance threshold
- Satellite pass prediction - real visibility windows (sunlit + observer-darkness checks) for any location on Earth
- Space weather (Kp index), current ISS location, scheduled rocket launches and NEO flybys- Search & filter by name, altitude band or object type (payload / rocket body / debris)

### Solar System
- Real Keplerian orbital mechanics for all 8 planets and their major moons (not simplified circles — actual elliptical orbits, correctly propagated over time)
- Adjustable simulation speed, click any body for physical data (radius, mass, orbital period)

### Exoplanets
- Live data from NASA's Exoplanet Archive: search any confirmed star system
- Earth Similarity Index scoring and habitable-zone visualization for every planet in a system
- Realistic, physically-informed coloring based on planet type and equilibrium temperature

---

## Tech stack

**Backend:** FastAPI (Python), Skyfield (orbital mechanics / SGP4), real-time data from CelesTrak, NASA Exoplanet Archive, NASA NeoWs, NOAA SWPC, Launch Library

**Frontend:** Three.js, vanilla JavaScript

**Infra:** Docker (separate frontend/backend services), deployed on Render

---

## Running it locally

```bash
git clone https://github.com/aarush-paul/exodex-wrapper.git
cd exodex-wrapper
docker compose up --build
```
Open `http://localhost:8080`.

Or without Docker:
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```
Then open `frontend/index.html` directly in a browser.

## Data sources

[CelesTrak](https://celestrak.org) (satellite TLEs) · [NASA Exoplanet Archive](https://exoplanetarchive.ipac.caltech.edu) · [NASA NeoWs](https://api.nasa.gov) · [NOAA SWPC](https://www.swpc.noaa.gov) · [Launch Library 2](https://thespacedevs.com) · [Skyfield](https://rhodesmill.org/skyfield/) for orbital propagation
