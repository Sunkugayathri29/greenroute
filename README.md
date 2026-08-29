# 🌿 GreenRoute AI — Intelligent Freight Route Optimization Engine

> AI-powered freight route optimization engine integrating vehicle parameters, dynamic payload load factors, fuel estimation, carbon emission modeling (CO₂), real-time traffic adjustment, and post-trip analytics.

---

## 🚀 Key Features

* 📍 **Place-Name & Geocoding Intelligence:** Geocode place names globally (*e.g., "Hyderabad" $\rightarrow$ "Bengaluru"*) using an async dual-tier geocoding chain (Photon + Nominatim) with zero API keys.
* 🚛 **Vehicle-Parameter-Aware Engine:** Calculates fuel & CO₂ emissions based on:
  * Vehicle Type (*Heavy Freight Truck / Medium Truck / Light Van*)
  * Dynamic Payload Weight Load Factor ($1.0\times$ to $1.3\times$ based on cargo weight)
  * Fuel Type (*Diesel / Petrol / CNG / Electric / Hybrid*)
  * Emission Standards (*BS-VI / BS-V / BS-IV / BS-III / Euro VI*)
* 🟢 **2-Corridor Multi-Route Classification:** Renders 2 candidate routes simultaneously on MapLibre GL JS:
  * 🟢 **Greenest Route:** Lowest CO₂ emissions
  * 🔵 **Optimal Route:** Recommended speed-cost-carbon balance
* 🛰️ **3 Map Modes:** Toggle between 🗺️ **Street**, 🚦 **Traffic** (Dark mode), and 🛰️ **Satellite** (Esri World Imagery) basemaps.
* 🚚 **Live Journey Simulation:** Simulates delivery truck transit along polyline coordinates with real-time distance, speed, and fuel telemetry HUD.
* 📊 **Post-Trip ESG Dashboard:** Interactive post-delivery analytics showcasing fuel saved, CO₂ avoided, trip cost in ₹ INR, and downloadable ESG compliance certificates.
* ⚙️ **Fleet Admin Portal:** Company config portal to manage company branding, vehicle registration plates, assigned drivers, and live fleet tracking.
* 🎨 **3 Custom Themes:** Emerald Light, Midnight Dark, and Cyber Fleet modes.

---

## 🛠️ Tech Stack

* **Backend:** Python 3.12, FastAPI 0.115, Uvicorn, HTTPX, Pydantic v2
* **Frontend:** HTML5, CSS3, Vanilla JavaScript (ES2022)
* **Map Engine:** MapLibre GL JS v4.7.1
* **Routing & Map Data:** OSRM (Open Source Routing Machine), OpenStreetMap, Carto, Esri
* **API Cost:** 100% Free & Open-Source — **Zero API keys required**

---

## 💻 Quick Start

### 1. Clone the repository
```bash
git clone https://github.com/shaikrohit/GreenRoute.git
cd GreenRoute
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the server
```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

### 4. Open in browser
Visit **[http://127.0.0.1:8000](http://127.0.0.1:8000)**

---

## 🧮 Mathematical Model

### 1. Dynamic Load Factor ($\text{LF}$)
$$\text{LF} = 1.0 + \left( \frac{\min(W_{payload}, W_{max})}{W_{max}} \right) \times 0.30$$

### 2. Fuel Consumption ($F_{total}$)
$$F_{total} = \frac{\text{Base Rate} \times \text{Vehicle Mult} \times \text{LF} \times \text{Distance}}{100}$$

### 3. CO₂ Emissions ($\text{CO}_2$)
$$\text{CO}_2 = F_{total} \times \text{Emission Factor} \times \text{Euro/BS Multiplier}$$

---

## 📄 License
Open-source under MIT License. Built for Freight Sustainability & Green Logistics.
