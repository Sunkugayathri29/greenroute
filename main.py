"""
GreenRoute Fleet Optimization Backend
FastAPI server — handles geocoding, routing, fuel/CO2 calculation
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional, List
import httpx
import asyncio
import math
import os

app = FastAPI(title="GreenRoute", version="1.0.0")


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Pydantic Models
# ─────────────────────────────────────────────────────────────

from db_manager import db_manager

class TruckParams(BaseModel):
    vehicle_type: str = "Heavy Freight Truck"   # Heavy Freight Truck / Medium Truck / Light Van
    payload_kg: float = 10000                   # kg
    fuel_type: str = "diesel"                   # diesel / cng / electric / hybrid
    vehicle_weight_kg: float = 25000            # gross vehicle weight in kg
    euro_class: str = "Euro VI"                 # Euro III / IV / V / VI

class RouteRequest(BaseModel):
    origin: str
    destination: str
    truck: TruckParams

class CoordRouteRequest(BaseModel):
    origin_lat: float
    origin_lon: float
    dest_lat: float
    dest_lon: float
    truck: TruckParams

class CompanyConfigPayload(BaseModel):
    company_name: str = "GreenLogistics India Pvt Ltd"
    fleet_id: str = "IN-FLEET-8842"
    hub_city: str = "Hyderabad Hub"
    assigned_driver: str = "Ramesh Kumar"
    vehicle_plate: str = "TS 09 EA 4521"

class FleetVehiclePayload(BaseModel):
    vehicle_plate: str
    driver_name: str
    vehicle_type: str
    route_corridor: str
    status: str = "In Transit"
    fuel_consumed: float = 0.0
    fuel_unit: str = "L"
    co2_saved_kg: float = 0.0

class TripLogPayload(BaseModel):
    origin: str
    destination: str
    vehicle_type: str
    payload_kg: float
    fuel_type: str
    euro_class: str
    distance_km: float
    duration_s: float
    fuel_consumed: float
    fuel_unit: str
    co2_emitted_kg: float
    trip_cost_inr: float




# ─────────────────────────────────────────────────────────────
# Emission & Fuel Constants
# ─────────────────────────────────────────────────────────────

FUEL_CONFIGS = {
    "diesel": {
        "base_consumption_per_100km": 28.0,   # L/100km for HGV at reference load
        "co2_per_litre": 2.68,                # kg CO2 per litre diesel
        "cost_per_litre": 92.0,               # ₹/litre (India avg)
        "unit": "L",
    },
    "petrol": {
        "base_consumption_per_100km": 26.0,   # L/100km for petrol truck/van
        "co2_per_litre": 2.31,                # kg CO2 per litre petrol
        "cost_per_litre": 102.0,              # ₹/litre (India avg petrol)
        "unit": "L",
    },
    "cng": {
        "base_consumption_per_100km": 22.0,   # kg/100km
        "co2_per_litre": 2.22,                # kg CO2 per kg CNG
        "cost_per_litre": 75.0,               # ₹/kg
        "unit": "kg",
    },
    "electric": {
        "base_consumption_per_100km": 120.0,  # kWh/100km
        "co2_per_litre": 0.72,                # kg CO2 per kWh (India grid avg)
        "cost_per_litre": 8.5,                # ₹/kWh
        "unit": "kWh",
    },
    "hybrid": {
        "base_consumption_per_100km": 18.0,   # L/100km
        "co2_per_litre": 2.68,
        "cost_per_litre": 92.0,
        "unit": "L",
    },
}

EURO_CO2_MULTIPLIERS = {
    "Euro III": 1.30,
    "Euro IV":  1.15,
    "Euro V":   1.05,
    "Euro VI":  1.00,
    "BS-III / Euro III": 1.30,
    "BS-IV / Euro IV":   1.15,
    "BS-V / Euro V":     1.05,
    "BS-VI / Euro VI":   1.00,
}

VEHICLE_BASE_CONSUMPTION = {
    "Heavy Freight Truck": 1.0,    # reference multiplier
    "Medium Truck":        0.72,
    "Light Van":           0.45,
}

TRAFFIC_MULTIPLIERS = {
    "light":  1.00,
    "medium": 1.18,
    "heavy":  1.42,
}

# ─────────────────────────────────────────────────────────────
# Fuel / CO2 / Cost Calculator
# ─────────────────────────────────────────────────────────────

def calculate_metrics(distance_km: float, duration_seconds: float, truck: TruckParams, traffic: str = "medium") -> dict:
    """Return fuel, co2, cost and adjusted ETA based on truck params + traffic."""
    fuel_cfg = FUEL_CONFIGS.get(truck.fuel_type, FUEL_CONFIGS["diesel"])
    vehicle_mult = VEHICLE_BASE_CONSUMPTION.get(truck.vehicle_type, 1.0)
    euro_mult = EURO_CO2_MULTIPLIERS.get(truck.euro_class, 1.0)
    traffic_mult = TRAFFIC_MULTIPLIERS.get(traffic, 1.18)

    # Load factor: heavier payload → higher consumption (up to +30% at max load)
    # Max payload reference: 20000 kg for HGV
    max_payload = {"Heavy Freight Truck": 20000, "Medium Truck": 10000, "Light Van": 3500}.get(truck.vehicle_type, 20000)
    load_factor = 1.0 + (min(truck.payload_kg, max_payload) / max_payload) * 0.30

    base = fuel_cfg["base_consumption_per_100km"]
    consumption_per_100km = base * vehicle_mult * load_factor
    total_fuel = (consumption_per_100km * distance_km) / 100.0

    co2_kg = total_fuel * fuel_cfg["co2_per_litre"] * euro_mult
    cost_inr = total_fuel * fuel_cfg["cost_per_litre"]

    # Adjust ETA for traffic
    adjusted_duration = duration_seconds * traffic_mult
    hours = int(adjusted_duration // 3600)
    minutes = int((adjusted_duration % 3600) // 60)
    eta_str = f"{hours}h {minutes:02d}m"

    return {
        "fuel": round(total_fuel, 1),
        "fuel_unit": fuel_cfg["unit"],
        "co2_kg": round(co2_kg, 1),
        "cost_inr": round(cost_inr),
        "eta": eta_str,
        "eta_seconds": int(adjusted_duration),
        "traffic": traffic,
        "load_factor": round(load_factor, 2),
    }


def classify_routes(routes_raw: list, truck: TruckParams) -> list:
    """
    Given a list of raw OSRM routes, calculate metrics and classify them as:
    Greenest, Optimal (Balanced).
    Returns exactly 2 route objects with color + label assigned.
    """
    traffic_levels = ["light", "medium"]
    enriched = []

    for i, r in enumerate(routes_raw[:2]):
        dist_km = r["distance"] / 1000.0
        dur_s = r["duration"]
        traffic = traffic_levels[i % len(traffic_levels)]
        metrics = calculate_metrics(dist_km, dur_s, truck, traffic)
        enriched.append({
            "distance_km": round(dist_km, 1),
            "duration_s": dur_s,
            "geometry": r.get("geometry", {}),
            "legs": r.get("legs", []),
            **metrics,
        })

    if len(enriched) < 2:
        # Synthesize extra variants if OSRM only returned 1 route
        base = enriched[0]
        while len(enriched) < 2:
            idx = len(enriched)
            factor = [1.0, 1.05][idx]
            traffic = traffic_levels[idx]
            dist = base["distance_km"] * factor
            dur = int(base["duration_s"] * factor)
            m = calculate_metrics(dist, dur, truck, traffic)
            enriched.append({
                "distance_km": round(dist, 1),
                "duration_s": dur,
                "geometry": base["geometry"],
                "legs": base["legs"],
                **m,
            })

    # Assign labels — Greenest and Optimal
    # Sort by CO2: index 0 = greenest
    by_co2 = sorted(range(len(enriched)), key=lambda i: enriched[i]["co2_kg"])

    labels = {}
    labels[by_co2[0]] = ("greenest", "🌱 Greenest", "#16a34a", "Lowest CO₂ emissions")

    # Optimal: whatever is left
    for j in range(len(enriched)):
        if j not in labels:
            labels[j] = ("optimal", "⭐ Optimal", "#2563eb", "Best overall balance")

    result = []
    for i, r in enumerate(enriched):
        label_key, label_text, color, reason = labels[i]
        result.append({
            **r,
            "type": label_key,
            "label": label_text,
            "color": color,
            "reason": reason,
        })

    return result

# ─────────────────────────────────────────────────────────────
# Geocoding & Routing Caches for High Speed
# ─────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────
# Geocoding & Routing Caches for High Speed
# ─────────────────────────────────────────────────────────────

GEOCODE_CACHE = {
    "hyderabad": {"lat": 17.3850, "lon": 78.4867, "display_name": "Hyderabad, Telangana, India", "short_name": "Hyderabad"},
    "bengaluru": {"lat": 12.9716, "lon": 77.5946, "display_name": "Bengaluru, Karnataka, India", "short_name": "Bengaluru"},
    "bangalore": {"lat": 12.9716, "lon": 77.5946, "display_name": "Bengaluru, Karnataka, India", "short_name": "Bengaluru"},
    "chennai": {"lat": 13.0827, "lon": 80.2707, "display_name": "Chennai, Tamil Nadu, India", "short_name": "Chennai"},
    "mumbai": {"lat": 19.0760, "lon": 72.8777, "display_name": "Mumbai, Maharashtra, India", "short_name": "Mumbai"},
    "delhi": {"lat": 28.6139, "lon": 77.2090, "display_name": "Delhi, India", "short_name": "Delhi"},
    "new delhi": {"lat": 28.6139, "lon": 77.2090, "display_name": "New Delhi, India", "short_name": "New Delhi"},
    "vijayawada": {"lat": 16.5062, "lon": 80.6480, "display_name": "Vijayawada, Andhra Pradesh, India", "short_name": "Vijayawada"},
    "visakhapatnam": {"lat": 17.6868, "lon": 83.2185, "display_name": "Visakhapatnam, Andhra Pradesh, India", "short_name": "Visakhapatnam"},
    "coimbatore": {"lat": 11.0168, "lon": 76.9558, "display_name": "Coimbatore, Tamil Nadu, India", "short_name": "Coimbatore"},
    "kolkata": {"lat": 22.5726, "lon": 88.3639, "display_name": "Kolkata, West Bengal, India", "short_name": "Kolkata"},
    "pune": {"lat": 18.5204, "lon": 73.8567, "display_name": "Pune, Maharashtra, India", "short_name": "Pune"},
    "ahmedabad": {"lat": 23.0225, "lon": 72.5714, "display_name": "Ahmedabad, Gujarat, India", "short_name": "Ahmedabad"},
    "surat": {"lat": 21.1702, "lon": 72.8311, "display_name": "Surat, Gujarat, India", "short_name": "Surat"},
    "jaipur": {"lat": 26.9124, "lon": 75.7873, "display_name": "Jaipur, Rajasthan, India", "short_name": "Jaipur"},
    "lucknow": {"lat": 26.8467, "lon": 80.9462, "display_name": "Lucknow, Uttar Pradesh, India", "short_name": "Lucknow"},
    "kanpur": {"lat": 26.4499, "lon": 80.3319, "display_name": "Kanpur, Uttar Pradesh, India", "short_name": "Kanpur"},
    "nagpur": {"lat": 21.1458, "lon": 79.0882, "display_name": "Nagpur, Maharashtra, India", "short_name": "Nagpur"},
    "indore": {"lat": 22.7196, "lon": 75.8577, "display_name": "Indore, Madhya Pradesh, India", "short_name": "Indore"},
    "bhopal": {"lat": 23.2599, "lon": 77.4126, "display_name": "Bhopal, Madhya Pradesh, India", "short_name": "Bhopal"},
    "patna": {"lat": 25.5941, "lon": 85.1376, "display_name": "Patna, Bihar, India", "short_name": "Patna"},
    "vadodara": {"lat": 22.3072, "lon": 73.1812, "display_name": "Vadodara, Gujarat, India", "short_name": "Vadodara"},
    "kochi": {"lat": 9.9312, "lon": 76.2673, "display_name": "Kochi, Kerala, India", "short_name": "Kochi"},
    "thiruvananthapuram": {"lat": 8.5241, "lon": 76.9366, "display_name": "Thiruvananthapuram, Kerala, India", "short_name": "Thiruvananthapuram"},
    "mysuru": {"lat": 12.2958, "lon": 76.6394, "display_name": "Mysuru, Karnataka, India", "short_name": "Mysuru"},
    "mysore": {"lat": 12.2958, "lon": 76.6394, "display_name": "Mysuru, Karnataka, India", "short_name": "Mysuru"},
    "madurai": {"lat": 9.9252, "lon": 78.1198, "display_name": "Madurai, Tamil Nadu, India", "short_name": "Madurai"},
    "tirupati": {"lat": 13.6288, "lon": 79.4192, "display_name": "Tirupati, Andhra Pradesh, India", "short_name": "Tirupati"},
    "warangal": {"lat": 17.9689, "lon": 79.5941, "display_name": "Warangal, Telangana, India", "short_name": "Warangal"},
    "hubballi": {"lat": 15.3647, "lon": 75.1240, "display_name": "Hubballi, Karnataka, India", "short_name": "Hubballi"},
    "chandigarh": {"lat": 30.7333, "lon": 76.7794, "display_name": "Chandigarh, India", "short_name": "Chandigarh"},
    "guwahati": {"lat": 26.1445, "lon": 91.7362, "display_name": "Guwahati, Assam, India", "short_name": "Guwahati"},
    "london": {"lat": 51.5074, "lon": -0.1278, "display_name": "London, UK", "short_name": "London"},
    "paris": {"lat": 48.8566, "lon": 2.3522, "display_name": "Paris, France", "short_name": "Paris"},
    "new york": {"lat": 40.7128, "lon": -74.0060, "display_name": "New York, USA", "short_name": "New York"},
    "dubai": {"lat": 25.2048, "lon": 55.2708, "display_name": "Dubai, UAE", "short_name": "Dubai"},
    "singapore": {"lat": 1.3521, "lon": 103.8198, "display_name": "Singapore", "short_name": "Singapore"},
}

ROUTE_CACHE = {}

def find_cached_fuzzy(query: str) -> Optional[dict]:
    """Find closest cached city using prefix/substring matching."""
    q = query.strip().lower()
    if not q:
        return None
    if q in GEOCODE_CACHE:
        return GEOCODE_CACHE[q]
    
    # Prefix match (e.g. 'bengalur' -> 'bengaluru')
    for key, val in GEOCODE_CACHE.items():
        if key.startswith(q) or q.startswith(key):
            return val
            
    # Substring match (e.g. 'new del' -> 'new delhi')
    for key, val in GEOCODE_CACHE.items():
        if q in key or key in q:
            return val
    return None

async def geocode_photon(place: str, limit: int = 5) -> List[dict]:
    """Search Photon API for matching places."""
    url = "https://photon.komoot.io/api/"
    params = {"q": place, "limit": limit}
    results = []
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            r = await client.get(url, params=params)
            data = r.json()
            features = data.get("features", [])
            for f in features:
                coords = f["geometry"]["coordinates"]
                props = f.get("properties", {})
                name = props.get("name") or props.get("city") or place
                country = props.get("country", "")
                state = props.get("state", "")
                city = props.get("city", "")
                parts = [p for p in [name, city if city != name else "", state, country] if p]
                disp = ", ".join(parts)
                results.append({
                    "lat": coords[1],
                    "lon": coords[0],
                    "display_name": disp if disp else name,
                    "short_name": name,
                })
    except Exception:
        pass
    return results

async def geocode_nominatim(place: str, limit: int = 5) -> List[dict]:
    """Search OpenStreetMap Nominatim for matching places."""
    url = "https://nominatim.openstreetmap.org/search"
    params = {"q": place, "format": "json", "limit": limit, "addressdetails": 1}
    headers = {"User-Agent": "GreenRoute/2.0 (fleet-logistics)"}

    results = []
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            r = await client.get(url, params=params, headers=headers)
            data = r.json()
            if isinstance(data, list):
                for d in data:
                    city_name = d.get("address", {}).get("city") or d.get("address", {}).get("town") or d.get("name", place)
                    results.append({
                        "lat": float(d["lat"]),
                        "lon": float(d["lon"]),
                        "display_name": d.get("display_name", place),
                        "short_name": city_name,
                    })
    except Exception:
        pass
    return results

async def get_autocomplete_suggestions(query: str, limit: int = 5) -> List[dict]:
    """Provide rich autocompletion suggestions matching user input."""
    q = query.strip().lower()
    if not q:
        return []

    suggestions = []
    seen = set()

    # 1. Local Instant Cache matches
    for key, val in GEOCODE_CACHE.items():
        if q in key or key.startswith(q):
            k = f"{round(val['lat'], 3)},{round(val['lon'], 3)}"
            if k not in seen:
                seen.add(k)
                suggestions.append({
                    "name": val["short_name"],
                    "display_name": val["display_name"],
                    "lat": val["lat"],
                    "lon": val["lon"],
                })

    # 2. Query Photon for live geographic suggestions
    if len(suggestions) < limit:
        photon_results = await geocode_photon(query, limit=limit)
        for p in photon_results:
            k = f"{round(p['lat'], 3)},{round(p['lon'], 3)}"
            if k not in seen:
                seen.add(k)
                suggestions.append({
                    "name": p["short_name"],
                    "display_name": p["display_name"],
                    "lat": p["lat"],
                    "lon": p["lon"],
                })
            if len(suggestions) >= limit:
                break

    # 3. Query Nominatim if still need suggestions
    if len(suggestions) < 3:
        nom_results = await geocode_nominatim(query, limit=3)
        for n in nom_results:
            k = f"{round(n['lat'], 3)},{round(n['lon'], 3)}"
            if k not in seen:
                seen.add(k)
                suggestions.append({
                    "name": n["short_name"],
                    "display_name": n["display_name"],
                    "lat": n["lat"],
                    "lon": n["lon"],
                })

    return suggestions[:limit]

async def geocode(place: str) -> dict:
    """Multi-tiered fuzzy geocoding that tolerates typos (e.g. 'Bengalur')."""
    clean = place.strip()
    key = clean.lower()

    # 1. Fast Cache Exact Match
    if key in GEOCODE_CACHE:
        return GEOCODE_CACHE[key]

    # 2. Fast Cache Fuzzy / Prefix Match
    fuzzy = find_cached_fuzzy(clean)
    if fuzzy:
        GEOCODE_CACHE[key] = fuzzy
        return fuzzy

    # 3. Live Photon Search
    photon_res = await geocode_photon(clean, limit=1)
    if photon_res:
        GEOCODE_CACHE[key] = photon_res[0]
        return photon_res[0]

    # 4. Live Nominatim Search
    nom_res = await geocode_nominatim(clean, limit=1)
    if nom_res:
        GEOCODE_CACHE[key] = nom_res[0]
        return nom_res[0]

    # 5. Typo correction (try stripping last 1-2 characters if user typed incomplete name)
    if len(clean) > 4:
        for trim in (clean[:-1], clean[:-2]):
            trimmed_fuzzy = find_cached_fuzzy(trim)
            if trimmed_fuzzy:
                GEOCODE_CACHE[key] = trimmed_fuzzy
                return trimmed_fuzzy
            trimmed_photon = await geocode_photon(trim, limit=1)
            if trimmed_photon:
                GEOCODE_CACHE[key] = trimmed_photon[0]
                return trimmed_photon[0]

    # 6. Fallback default instead of hard error
    fallback = GEOCODE_CACHE.get("hyderabad")
    return {
        "lat": fallback["lat"],
        "lon": fallback["lon"],
        "display_name": f"{clean} (Approximate location)",
        "short_name": clean,
    }


# ─────────────────────────────────────────────────────────────
# OSRM Routing
# ─────────────────────────────────────────────────────────────

async def get_osrm_routes(o_lat, o_lon, d_lat, d_lon) -> list:
    cache_key = f"{round(o_lat,4)},{round(o_lon,4)};{round(d_lat,4)},{round(d_lon,4)}"
    if cache_key in ROUTE_CACHE:
        return ROUTE_CACHE[cache_key]

    coords = f"{o_lon},{o_lat};{d_lon},{d_lat}"
    url = f"https://router.project-osrm.org/route/v1/driving/{coords}"
    params = {
        "alternatives": "true",
        "steps": "true",
        "geometries": "geojson",
        "overview": "full",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, params=params)
            data = r.json()
            if data.get("code") == "Ok":
                routes = data.get("routes", [])
                if routes:
                    ROUTE_CACHE[cache_key] = routes
                return routes
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Routing service error: {str(e)}")
    return []

# ─────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/places/autocomplete")
async def autocomplete_places(q: str = ""):
    """Return autocomplete suggestions for place search queries."""
    if not q or len(q.strip()) < 2:
        return {"suggestions": []}
    suggestions = await get_autocomplete_suggestions(q.strip(), limit=6)
    return {"suggestions": suggestions}


@app.post("/api/optimize")
async def optimize_route(req: RouteRequest):

    """Main endpoint: geocode + route + classify by truck params."""
    origin_geo, dest_geo = await asyncio.gather(
        geocode(req.origin),
        geocode(req.destination),
    )

    raw_routes = await get_osrm_routes(
        origin_geo["lat"], origin_geo["lon"],
        dest_geo["lat"], dest_geo["lon"],
    )
    if not raw_routes:
        raise HTTPException(status_code=404, detail="No routes found between these locations.")

    classified = classify_routes(raw_routes, req.truck)

    return {
        "origin": {
            "name": req.origin,
            "display": origin_geo["short_name"],
            "lat": origin_geo["lat"],
            "lon": origin_geo["lon"],
        },
        "destination": {
            "name": req.destination,
            "display": dest_geo["short_name"],
            "lat": dest_geo["lat"],
            "lon": dest_geo["lon"],
        },
        "truck": req.truck.dict(),
        "routes": classified,
    }


@app.post("/api/optimize-coords")
async def optimize_route_coords(req: CoordRouteRequest):
    """Route by coordinates (no geocoding needed)."""
    raw_routes = await get_osrm_routes(
        req.origin_lat, req.origin_lon,
        req.dest_lat, req.dest_lon,
    )
    if not raw_routes:
        raise HTTPException(status_code=404, detail="No routes found.")

    classified = classify_routes(raw_routes, req.truck)
    return {"routes": classified}


@app.get("/api/health")
async def health():
    db_status = await db_manager.get_status()
    return {"status": "ok", "service": "GreenRoute", "db": db_status}



# ─────────────────────────────────────────────────────────────
# Database & Cache Endpoints
# ─────────────────────────────────────────────────────────────

@app.get("/api/db/status")
async def get_db_status():
    return await db_manager.get_status()


@app.get("/api/db/config")
async def get_company_config():
    config = await db_manager.get_company_config()
    db_status = await db_manager.get_status()
    return {"config": config, "source": db_status["mode"]}


@app.post("/api/db/config")
async def save_company_config(payload: CompanyConfigPayload):
    saved = await db_manager.save_company_config(payload.dict())
    db_status = await db_manager.get_status()
    return {"config": saved, "source": db_status["mode"], "message": "Company configuration saved successfully"}


@app.get("/api/db/fleet")
async def get_fleet_vehicles():
    vehicles = await db_manager.get_fleet_vehicles()
    db_status = await db_manager.get_status()
    return {"vehicles": vehicles, "source": db_status["mode"]}


@app.post("/api/db/fleet")
async def add_fleet_vehicle(payload: FleetVehiclePayload):
    added = await db_manager.add_fleet_vehicle(payload.dict())
    db_status = await db_manager.get_status()
    return {"vehicle": added, "source": db_status["mode"], "message": "Vehicle added to fleet monitoring"}


@app.get("/api/db/metrics")
async def get_metrics():
    metrics = await db_manager.get_aggregated_metrics()
    db_status = await db_manager.get_status()
    return {"metrics": metrics, "source": db_status["mode"]}


@app.post("/api/db/trips")
async def record_trip(payload: TripLogPayload):
    trip = await db_manager.record_trip_log(payload.dict())
    db_status = await db_manager.get_status()
    return {"trip": trip, "source": db_status["mode"], "message": "Trip logged successfully"}



# ─────────────────────────────────────────────────────────────
# Serve Frontend
# ─────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def serve_index():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
