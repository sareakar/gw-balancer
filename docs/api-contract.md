# Contrato de API — GW Balancer Core

Base URL (laboratorio): `http://localhost:8000`  
Base URL (producción): `https://core.gwbalancer.example.com`

## Autenticación

Todas las requests (excepto `/health`) requieren el header:

```
X-API-Key: <api_key>
```

El API key identifica al tenant. Nunca se incluye `tenant_id` en el body.

**Keys de laboratorio:**
| Key | Rol |
|---|---|
| `lab-monitor-key-001` | Monitor (reporta estado de gateways) |
| `lab-adapter-key-001` | Adaptador Asterisk (pide decisiones de ruteo) |

---

## Endpoints

### `POST /v1/gateway-state`

Reporta el estado actual de un gateway. Usado exclusivamente por los monitores.

El estado se almacena en Redis con TTL de 60 segundos. Si el monitor deja de reportar, la entry expira y el gateway queda excluido de las decisiones de ruteo.

**Request:**
```http
POST /v1/gateway-state
X-API-Key: lab-monitor-key-001
Content-Type: application/json

{
  "gateway_slug": "gw-001",
  "snapshot": {
    "available_channels": 6,
    "total_channels": 8,
    "signal_rssi": -72,
    "active_calls": 2,
    "failure_rate_5m": 0.03,
    "registered": true
  }
}
```

**Campos del snapshot:**

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `available_channels` | int | sí | Canales libres en este momento |
| `total_channels` | int | sí | Capacidad total del gateway |
| `signal_rssi` | int | no | Señal en dBm. null si no disponible (se usa valor neutro 50 en scoring) |
| `active_calls` | int | no | Llamadas activas (default 0) |
| `failure_rate_5m` | float | no | Tasa de fallos últimos 5 min, 0.0–1.0 (default 0.0) |
| `registered` | bool | no | Si el gateway está registrado en red GSM (default true) |

**Respuesta exitosa:** `204 No Content`

**Errores:**
```
401  Invalid API key
422  Payload inválido (campo requerido faltante o tipo incorrecto)
```

---

### `POST /v1/route-decision`

Solicita la decisión de ruteo para una llamada. Usado por los adaptadores (AGI script).

El Core Engine lee el estado de todos los gateways del tenant desde Redis, los puntúa con el scoring engine, y devuelve el mejor gateway disponible. La decisión se registra en Postgres.

**Request:**
```http
POST /v1/route-decision
X-API-Key: lab-adapter-key-001
Content-Type: application/json

{
  "call_id": "1750800000.42"
}
```

| Campo | Tipo | Requerido | Descripción |
|---|---|---|---|
| `call_id` | string | no | ID de la llamada (agi_uniqueid en Asterisk). Se registra en el histórico. |

**Respuesta exitosa:** `200 OK`
```json
{
  "gateway_slug": "gw-002",
  "score": 82.7,
  "reason": "weighted_score",
  "alternatives": [
    {"gateway_slug": "gw-001", "score": 72.4},
    {"gateway_slug": "gw-003", "score": 61.1}
  ]
}
```

| Campo | Descripción |
|---|---|
| `gateway_slug` | Identificador del gateway elegido. Usar como trunk/peer en el dialplan. |
| `score` | Puntuación 0–100. Mayor es mejor. |
| `reason` | Razón de la decisión. Actualmente siempre `"weighted_score"`. |
| `alternatives` | Hasta 2 alternativas en orden descendente de score. Útil para fallback en el dialplan. |

**Errores:**
```
401  Invalid API key
404  No gateways configured for tenant  (el tenant no tiene gateways en Postgres)
503  No gateways currently reporting state  (ningún gateway tiene estado válido en Redis)
503  All gateways busy or offline  (todos tienen 0 canales disponibles o registered=false)
```

---

### `GET /v1/gateways`

Lista los gateways del tenant con su estado actual. Útil para monitoreo y debugging.

**Request:**
```http
GET /v1/gateways
X-API-Key: lab-adapter-key-001
```

**Respuesta:** `200 OK`
```json
[
  {
    "slug": "gw-001",
    "display_name": "Gateway GSM 01 (Dinstar)",
    "online": true,
    "state": {
      "available_channels": 6,
      "total_channels": 8,
      "signal_rssi": -72,
      "active_calls": 2,
      "failure_rate_5m": 0.03,
      "registered": true
    }
  },
  {
    "slug": "gw-003",
    "display_name": "Gateway GSM 03 (OpenVox)",
    "online": false,
    "state": null
  }
]
```

`online: false` significa que la key en Redis expiró — el monitor de ese gateway dejó de reportar hace más de 60 segundos.

---

### `GET /health`

Health check del servicio. No requiere autenticación.

```http
GET /health
```

```json
{"status": "ok"}
```

---

## Ciclo de vida de un gateway en el sistema

```
Monitor arranca
    │
    ▼
POST /v1/gateway-state cada 10s ──────────────────────────┐
    │                                                      │
    ▼                                                      │
Redis: tenant:{id}:gateway:{slug} = snapshot (TTL=60s)    │
    │                                                      │
    │   (si el monitor para, la key expira en 60s)         │
    │                                                      │
    ▼                                                      │
POST /v1/route-decision                                    │
    │                                                      │
    ├── gateway con key en Redis → elegible para scoring   │
    └── gateway sin key en Redis → excluido               │
                                                           │
                                              Monitor reporta de nuevo
                                              → key se renueva con TTL fresco
```

---

## Notas de implementación para adaptadores

**Timeout recomendado**: 2 segundos. Si el Core Engine no responde, el adaptador debe usar un trunk de fallback — nunca bloquear la llamada.

**Variables de canal en Asterisk** (seteadas por `agi_route.py`):

| Variable | Valor cuando hay éxito | Valor cuando falla |
|---|---|---|
| `GWB_GATEWAY` | Slug del gateway elegido (ej: `gw-002`) | Vacío `""` |
| `GWB_SCORE` | Score numérico (ej: `82.7`) | Vacío `""` |

**Variables de entorno requeridas para el AGI script:**

| Variable | Descripción | Ejemplo |
|---|---|---|
| `GWB_CORE_URL` | URL base del Core Engine | `https://core.gwbalancer.example.com` |
| `GWB_API_KEY` | API key del adaptador | `lab-adapter-key-001` |
| `GWB_TIMEOUT` | Timeout en segundos (default: 2) | `2` |
