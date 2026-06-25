# Laboratorio local — GW Balancer

El laboratorio levanta todos los componentes del sistema en contenedores locales usando `podman-compose`. El objetivo es validar el flujo completo (monitor → Core Engine → decisión) sin depender de hardware real ni de infraestructura en GCP.

## Qué se levanta

| Contenedor | Imagen | Puerto | Descripción |
|---|---|---|---|
| `postgres` | postgres:16 | 5432 | Base de datos con schema y seed de lab |
| `redis` | redis:7 | 6379 | Estado caliente de gateways |
| `core` | build local | 8000 | Core Engine (FastAPI) |
| `monitor-sim` | python:3.12-slim | — | Monitor simulado, reporta estado cada 10s |

---

## Prerequisitos

```bash
# Verificar que podman y podman-compose estén instalados
podman --version       # 4.x o superior
podman-compose --version
```

Si no tenés `podman-compose`:
```bash
pip install podman-compose
```

---

## Levantar el laboratorio

```bash
# 1. Pararse en el directorio del lab
cd lab

# 2. Copiar el archivo de variables de entorno
cp .env.example .env

# 3. Levantar todos los servicios
podman-compose up
```

La primera vez tarda unos minutos: descarga las imágenes de postgres y redis, y construye la imagen del Core Engine desde el Containerfile.

**Sequencia de arranque:**
1. Postgres arranca y ejecuta los scripts en `init-db/` (schema + seed)
2. Redis arranca
3. Core Engine arranca y conecta a Postgres y Redis
4. Monitor simulado arranca y empieza a reportar estado cada 10 segundos

Si querés correrlo en background:
```bash
podman-compose up -d
```

---

## Verificar que todo funciona

### 1. Health check del Core Engine

```bash
curl http://localhost:8000/health
```
Respuesta esperada: `{"status":"ok"}`

### 2. Ver el estado de los gateways

Después de ~15 segundos (el monitor ya reportó al menos una vez):

```bash
curl http://localhost:8000/v1/gateways \
  -H "X-API-Key: lab-adapter-key-001"
```

Respuesta esperada (los valores cambian con cada reporte del simulador):
```json
[
  {
    "slug": "gw-001",
    "display_name": "Gateway GSM 01 (Dinstar)",
    "online": true,
    "state": {
      "available_channels": 6,
      "total_channels": 8,
      "signal_rssi": -71,
      "active_calls": 2,
      "failure_rate_5m": 0.047,
      "registered": true
    }
  },
  {
    "slug": "gw-002",
    "display_name": "Gateway GSM 02 (Dinstar)",
    "online": true,
    "state": { ... }
  },
  {
    "slug": "gw-003",
    "display_name": "Gateway GSM 03 (OpenVox)",
    "online": true,
    "state": { ... }
  }
]
```

Si algún gateway aparece con `"online": false`, es porque el monitor todavía no reportó ese ciclo o el TTL de 60s expiró. Esperá 10 segundos y repetí.

### 3. Pedir una decisión de ruteo

```bash
curl -X POST http://localhost:8000/v1/route-decision \
  -H "X-API-Key: lab-adapter-key-001" \
  -H "Content-Type: application/json" \
  -d '{"call_id": "test-001"}'
```

Respuesta esperada:
```json
{
  "gateway_slug": "gw-002",
  "score": 82.7,
  "reason": "weighted_score",
  "alternatives": [
    {"gateway_slug": "gw-001", "score": 71.3},
    {"gateway_slug": "gw-003", "score": 65.1}
  ]
}
```

El gateway elegido varía con cada llamada porque el simulador genera valores distintos en cada ciclo.

### 4. Reportar estado manualmente (simular un monitor real)

```bash
curl -X POST http://localhost:8000/v1/gateway-state \
  -H "X-API-Key: lab-monitor-key-001" \
  -H "Content-Type: application/json" \
  -d '{
    "gateway_slug": "gw-001",
    "snapshot": {
      "available_channels": 4,
      "total_channels": 8,
      "signal_rssi": -85,
      "active_calls": 4,
      "failure_rate_5m": 0.10,
      "registered": true
    }
  }'
```

Respuesta: `204 No Content`

Inmediatamente después, `gw-001` tendrá peor score (señal baja, mitad de canales ocupados, más fallos). La próxima `/route-decision` debería elegir otro gateway.

### 5. Probar el health-check implícito por TTL

Para ver qué pasa cuando un gateway "se cae":

```bash
# Verificar estado actual
curl http://localhost:8000/v1/gateways -H "X-API-Key: lab-adapter-key-001" | python3 -m json.tool

# Esperar 65 segundos sin que el monitor reporte gw-003
# (Esto requiere modificar el simulador o hacerlo manualmente)

# Después de 65s, gw-003 aparecerá como online: false
# y /route-decision lo excluirá automáticamente
```

---

## Ver los logs

```bash
# Todos los servicios
podman-compose logs -f

# Solo el Core Engine
podman-compose logs -f core

# Solo el monitor simulado (muestra el estado que reporta cada 10s)
podman-compose logs -f monitor-sim
```

El monitor simulado loguea algo así:
```
2026-06-25 10:00:10 INFO gw-001  ch=6/8  rssi=-71  fail=4.7%  reg=True
2026-06-25 10:00:10 INFO gw-002  ch=8/16 rssi=-63  fail=1.2%  reg=True
2026-06-25 10:00:10 INFO gw-003  ch=3/4  rssi=-88  fail=8.9%  reg=True
```

---

## Inspeccionar la base de datos

```bash
# Conectarse a Postgres
podman exec -it lab-postgres-1 psql -U gwb -d gwbalancer

# Ver el catálogo de gateways
SELECT slug, display_name, cost_per_minute FROM gateways;

# Ver el histórico de decisiones tomadas
SELECT gateway_slug, score, reason, decided_at
FROM route_decisions
ORDER BY decided_at DESC
LIMIT 20;

# Ver distribución de decisiones por gateway
SELECT gateway_slug, COUNT(*), AVG(score)::numeric(5,2)
FROM route_decisions
GROUP BY gateway_slug
ORDER BY COUNT(*) DESC;

# Salir
\q
```

---

## Inspeccionar Redis

```bash
# Conectarse a Redis
podman exec -it lab-redis-1 redis-cli

# Ver todas las keys del tenant de lab
KEYS tenant:00000000-0000-0000-0000-000000000001:*

# Ver el estado de un gateway específico
GET tenant:00000000-0000-0000-0000-000000000001:gateway:gw-001

# Ver cuántos segundos le quedan a la key antes de expirar
TTL tenant:00000000-0000-0000-0000-000000000001:gateway:gw-001

# Salir
exit
```

---

## Detener el laboratorio

```bash
# Detener y eliminar contenedores (conserva los volúmenes — los datos persisten)
podman-compose down

# Detener y eliminar todo, incluyendo los datos de Postgres
podman-compose down -v
```

---

## Datos del laboratorio (seed)

El archivo `lab/init-db/02-seed.sql` crea:

**Tenant:** `lab-tenant` (UUID: `00000000-0000-0000-0000-000000000001`)

**API keys:**
| Key | Label | Usar con |
|---|---|---|
| `lab-monitor-key-001` | Simulated Monitor | `POST /v1/gateway-state` |
| `lab-adapter-key-001` | Asterisk AGI Adapter | `POST /v1/route-decision`, `GET /v1/gateways` |

**Gateways:**
| Slug | Display name | Costo/min |
|---|---|---|
| `gw-001` | Gateway GSM 01 (Dinstar) | $0.0100 |
| `gw-002` | Gateway GSM 02 (Dinstar) | $0.0080 ← más barato |
| `gw-003` | Gateway GSM 03 (OpenVox) | $0.0120 ← más caro |

El scoring favorece `gw-002` por costo, pero si tiene peor señal o más canales ocupados que `gw-001`, puede perder. El monitor simulado introduce suficiente variación para ver ambos casos.

---

## Problemas comunes

**`core` no arranca — "connection refused" a Postgres o Redis**  
Los healthchecks deberían prevenir esto, pero si ocurre: `podman-compose restart core`

**El monitor aparece con error "connection refused"**  
El `core` tardó más de lo esperado en arrancar. El simulador reintenta automáticamente; en ~30 segundos debería conectar.

**`GET /v1/gateways` devuelve todos con `online: false`**  
El monitor todavía no reportó. Esperar 10–15 segundos.

**`POST /v1/route-decision` devuelve 503**  
Todos los gateways están sin estado en Redis o con 0 canales disponibles. Ver logs del monitor-sim.

**Cambios en el código del Core Engine**  
```bash
podman-compose build core
podman-compose up -d core
```
