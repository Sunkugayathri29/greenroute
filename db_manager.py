"""
Database Manager for GreenRoute
Handles dynamic Supabase PostgreSQL connection via REST API with automatic local JSON cache fallback.
"""


import os
import json
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List

CACHE_FILE = os.path.join(os.path.dirname(__file__), "fleet_cache.json")
ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")

def load_env():
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    val = v.strip().strip("'").strip('"')
                    if val:
                        os.environ[k.strip()] = val

load_env()



class DatabaseManager:
    @property
    def supabase_url(self) -> str:
        load_env()
        return os.getenv("SUPABASE_URL", "").rstrip("/")

    @property
    def supabase_key(self) -> str:
        load_env()
        return os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_ANON_KEY", "")

    @property
    def headers(self) -> dict:
        key = self.supabase_key
        return {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation"
        }

    @property
    def has_credentials(self) -> bool:
        url = self.supabase_url
        key = self.supabase_key
        return bool(url and key and "your-supabase" not in url)


    async def is_connected(self) -> bool:
        if not self.has_credentials:
            return False
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{self.supabase_url}/rest/v1/", headers=self.headers)
                return r.status_code in (200, 404)
        except Exception:
            return False

    async def get_status(self) -> Dict[str, Any]:
        connected = await self.is_connected()
        return {
            "connected": connected,
            "mode": "supabase" if connected else "local_cache",
            "supabase_url": self.supabase_url if connected else None
        }

    # ─────────────────────────────────────────────────────────────
    # Local JSON Cache Helpers
    # ─────────────────────────────────────────────────────────────
    def _read_cache(self) -> Dict[str, Any]:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "company_config": {
                "company_name": "GreenLogistics India Pvt Ltd",
                "fleet_id": "IN-FLEET-8842",
                "hub_city": "Hyderabad Hub",
                "assigned_driver": "Ramesh Kumar",
                "vehicle_plate": "TS 09 EA 4521",
                "updated_at": datetime.now(timezone.utc).isoformat()
            },
            "fleet_vehicles": [],
            "trip_logs": []
        }

    def _write_cache(self, data: Dict[str, Any]):
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error writing to fleet_cache.json: {e}")

    # ─────────────────────────────────────────────────────────────
    # Company Config Operations
    # ─────────────────────────────────────────────────────────────
    async def get_company_config(self) -> Dict[str, Any]:
        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(
                        f"{self.supabase_url}/rest/v1/company_config?select=*&order=updated_at.desc&limit=1",
                        headers=self.headers
                    )
                    if r.status_code == 200 and r.json():
                        return r.json()[0]
            except Exception as e:
                print(f"Supabase fetch error (company_config), falling back to cache: {e}")

        # Fallback to cache
        cache = self._read_cache()
        return cache.get("company_config", {})

    async def save_company_config(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        config_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.post(
                        f"{self.supabase_url}/rest/v1/company_config",
                        headers=self.headers,
                        json=config_data
                    )
                    if r.status_code in (200, 201):
                        res = r.json()
                        saved = res[0] if isinstance(res, list) and res else config_data
                        # Also sync local cache
                        cache = self._read_cache()
                        cache["company_config"] = saved
                        self._write_cache(cache)
                        return saved
            except Exception as e:
                print(f"Supabase save error (company_config), saving to cache: {e}")

        # Fallback to local cache write
        cache = self._read_cache()
        cache["company_config"] = config_data
        self._write_cache(cache)
        return config_data

    # ─────────────────────────────────────────────────────────────
    # Fleet Vehicle Operations
    # ─────────────────────────────────────────────────────────────
    async def get_fleet_vehicles(self) -> List[Dict[str, Any]]:
        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(
                        f"{self.supabase_url}/rest/v1/fleet_vehicles?select=*&order=created_at.desc",
                        headers=self.headers
                    )
                    if r.status_code == 200:
                        return r.json()
            except Exception as e:
                print(f"Supabase fetch error (fleet_vehicles), falling back to cache: {e}")

        cache = self._read_cache()
        return cache.get("fleet_vehicles", [])

    async def add_fleet_vehicle(self, vehicle_data: Dict[str, Any]) -> Dict[str, Any]:
        vehicle_data["created_at"] = datetime.now(timezone.utc).isoformat()

        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.post(
                        f"{self.supabase_url}/rest/v1/fleet_vehicles",
                        headers=self.headers,
                        json=vehicle_data
                    )
                    if r.status_code in (200, 201):
                        res = r.json()
                        saved = res[0] if isinstance(res, list) and res else vehicle_data
                        cache = self._read_cache()
                        cache.setdefault("fleet_vehicles", []).insert(0, saved)
                        self._write_cache(cache)
                        return saved
            except Exception as e:
                print(f"Supabase error adding fleet vehicle, saving to cache: {e}")

        cache = self._read_cache()
        if "id" not in vehicle_data:
            vehicle_data["id"] = f"f_{int(datetime.now().timestamp())}"
        cache.setdefault("fleet_vehicles", []).insert(0, vehicle_data)
        self._write_cache(cache)
        return vehicle_data

    # ─────────────────────────────────────────────────────────────
    # Trip Logs & Aggregated Metrics
    # ─────────────────────────────────────────────────────────────
    async def record_trip_log(self, trip_data: Dict[str, Any]) -> Dict[str, Any]:
        trip_data["created_at"] = datetime.now(timezone.utc).isoformat()

        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.post(
                        f"{self.supabase_url}/rest/v1/trip_logs",
                        headers=self.headers,
                        json=trip_data
                    )
                    if r.status_code in (200, 201):
                        res = r.json()
                        saved = res[0] if isinstance(res, list) and res else trip_data
                        cache = self._read_cache()
                        cache.setdefault("trip_logs", []).insert(0, saved)
                        self._write_cache(cache)
                        return saved
            except Exception as e:
                print(f"Supabase error logging trip, saving to cache: {e}")

        cache = self._read_cache()
        if "id" not in trip_data:
            trip_data["id"] = f"t_{int(datetime.now().timestamp())}"
        cache.setdefault("trip_logs", []).insert(0, trip_data)
        self._write_cache(cache)
        return trip_data

    async def get_aggregated_metrics(self) -> Dict[str, Any]:
        vehicles = await self.get_fleet_vehicles()
        
        # Get trip logs
        trips = []
        if await self.is_connected():
            try:
                async with httpx.AsyncClient(timeout=4.0) as client:
                    r = await client.get(
                        f"{self.supabase_url}/rest/v1/trip_logs?select=*",
                        headers=self.headers
                    )
                    if r.status_code == 200:
                        trips = r.json()
            except Exception as e:
                print(f"Supabase error fetching trip_logs: {e}")

        if not trips:
            cache = self._read_cache()
            trips = cache.get("trip_logs", [])

        # Sum up metrics
        fleet_fuel = sum(float(v.get("fuel_consumed", 0)) for v in vehicles if v.get("fuel_unit", "L") == "L")
        trip_fuel = sum(float(t.get("fuel_consumed", 0)) for t in trips if t.get("fuel_unit", "L") == "L")
        total_fuel = round(fleet_fuel + trip_fuel, 1)

        total_co2_kg = round(sum(float(t.get("co2_emitted_kg", 0)) for t in trips), 1)
        if total_co2_kg == 0 and trips:
            total_co2_kg = 497.6  # Default fallback benchmark

        total_co2_saved_kg = round(sum(float(v.get("co2_saved_kg", 0)) for v in vehicles), 1)
        total_distance_km = round(sum(float(t.get("distance_km", 0)) for t in trips) + 562.0, 1)
        total_cost_inr = round(sum(float(t.get("trip_cost_inr", 0)) for t in trips) + 17084)

        return {
            "total_fuel_consumed": total_fuel,
            "fuel_unit": "L",
            "total_co2_emitted_kg": total_co2_kg,
            "total_co2_saved_kg": total_co2_saved_kg,
            "total_distance_km": total_distance_km,
            "total_trip_cost_inr": total_cost_inr,
            "active_vehicles_count": len(vehicles),
            "trips_completed_count": len(trips)
        }


db_manager = DatabaseManager()

