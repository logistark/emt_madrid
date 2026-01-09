# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Home Assistant custom component that provides real-time bus arrival information for Madrid's EMT (Empresa Municipal de Transportes) public transportation system. Creates sensors that show arrival times for specific bus lines at designated stops using the EMT MobilityLabs API.

## Development Commands

**Run tests:**
```bash
pytest tests/
```

**Run a single test:**
```bash
pytest tests/test_sensor.py::test_valid_config
```

**Local development with Home Assistant:**
```bash
docker-compose up
# Access Home Assistant at http://localhost:8124
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Home Assistant Core (sensor platform)                   │
│  sensor.py - BusLineSensor extends Entity               │
└─────────────────────┬───────────────────────────────────┘
                      │ Uses APIEMT instance
                      ▼
┌─────────────────────────────────────────────────────────┐
│  EMT API Client (emt_madrid.py - APIEMT class)         │
│  - Token management and authentication                  │
│  - API request/response handling                        │
│  - Stop and arrival data parsing                        │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP via requests
                      ▼
┌─────────────────────────────────────────────────────────┐
│  EMT MobilityLabs REST API                              │
│  https://openapi.emtmadrid.es/                          │
└─────────────────────────────────────────────────────────┘
```

### Key Files

- **`custom_components/emt_madrid/emt_madrid.py`** - APIEMT class handles all EMT API communication: authentication, fetching stop info, arrival times. Contains fallback logic for missing endpoints.

- **`custom_components/emt_madrid/sensor.py`** - BusLineSensor entity that Home Assistant manages. Creates one sensor per bus line at a stop. State is arrival time in minutes; attributes contain destination, origin, frequency, distance, etc.

### API Response Codes

The EMT API uses specific response codes: `01` = success, `80` = invalid token, `81` = endpoint unavailable (triggers fallback), `90` = stop disabled, `98` = API rate limit.

### Sensor Behavior

- Updates approximately every minute
- State: next arrival time in minutes (capped at 45, "unknown" if no bus)
- Stop info endpoint has fallback to "around stop" endpoint if primary returns code 81

## Configuration

Users configure via Home Assistant YAML with email, password, stop ID, and optional line filter. Schema validation uses voluptuous.
