# Arquitectura — GW Balancer

## Problema que resuelve

En instalaciones con múltiples gateways GSM, las llamadas salientes se distribuyen con lógica estática: round-robin fijo u orden de trunk. Esta lógica ignora el estado real del hardware en el momento de la llamada.

Consecuencias comunes:
- Llamadas fallidas porque el gateway seleccionado tiene poca señal o todos sus canales ocupados
- Gateways disponibles que quedan sin usar mientras otro está saturado
- Sin visibilidad del estado real de la red GSM en tiempo real

GW Balancer agrega una capa de decisión inteligente entre el discador y los gateways, usando el estado real de cada gateway para elegir el mejor en cada llamada.

---

## Visión general

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Red del cliente                             │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │  Gateway GSM │    │  Gateway GSM │    │  Gateway GSM         │  │
│  │    gw-001    │    │    gw-002    │    │    gw-003            │  │
│  └──────┬───────┘    └──────┬───────┘    └──────────┬───────────┘  │
│         │ SNMP/HTTP         │ SNMP/HTTP             │ SNMP/HTTP    │
│         └──────────┬────────┘───────────────────────┘              │
│                    │                                                │
│           ┌────────▼────────┐    ┌──────────────────────────────┐  │
│           │    Monitor      │    │    Asterisk / AsterVoIP      │  │
│           │  (por marca)    │    │                              │  │
│           └────────┬────────┘    │  Dialplan →                 │  │
│                    │             │    AGI(agi_route.py)         │  │
│                    │             │      ↓                       │  │
│                    │             │    Dial(SIP/${GWB_GATEWAY})  │  │
│                    │             └──────────────┬───────────────┘  │
└────────────────────┼────────────────────────────┼──────────────────┘
                     │ POST /v1/gateway-state      │ POST /v1/route-decision
                     │ (reporte de estado)         │ (pedido de ruteo)
                     │                             │
              ┌──────▼─────────────────────────────▼──────┐
              │           Core Engine (GCP Cloud Run)      │
              │                 FastAPI                    │
              │                                            │
              │  ┌─────────────┐    ┌──────────────────┐  │
              │  │    Redis    │    │     Postgres      │  │
              │  │  (estado    │    │  (catálogo,       │  │
              │  │   caliente) │    │   config,         │  │
              │  │   TTL=60s   │    │   histórico)      │  │
              │  └─────────────┘    └──────────────────┘  │
              └────────────────────────────────────────────┘
```

**Principio de diseño fundamental**: el Core Engine nunca sabe de sintaxis de PBX ni de protocolos de gateways. Solo recibe estado normalizado y devuelve un `gateway_slug`. Toda la traducción vive en los bordes (monitores y adaptadores), que son intercambiables sin tocar el núcleo.

---

## Componentes

### 1. Core Engine (`core/`)

El cerebro del sistema. Corre en GCP Cloud Run y expone una API REST.

**Responsabilidades:**
- Recibir snapshots de estado de los monitores y almacenarlos en Redis
- Cuando un adaptador pide una decisión de ruteo, leer el estado actual de todos los gateways del tenant desde Redis, puntuar cada uno con el scoring engine, y devolver el mejor
- Registrar cada decisión en Postgres para histórico y observabilidad
- Autenticar todas las requests por API key y resolver el `tenant_id` correspondiente

**Lo que NO hace:**
- No conoce el protocolo de ningún gateway (eso es responsabilidad del monitor)
- No conoce la sintaxis de ninguna PBX (eso es responsabilidad del adaptador)
- No toma decisiones proactivas: responde a requests (pull, no push)

**Estructura interna:**
```
core/app/
├── main.py          # App FastAPI, lifespan (conexiones a Redis y Postgres)
├── config.py        # Settings via pydantic-settings (env vars)
├── api/v1/
│   ├── routes.py    # Los 3 endpoints + dependency de autenticación
│   └── schemas.py   # Modelos Pydantic de request/response
├── domain/
│   ├── models.py    # GatewaySnapshot, GatewayScore (dataclasses)
│   └── scoring.py   # Scoring engine — el algoritmo de decisión
└── infra/
    ├── redis_client.py   # Operaciones Redis con namespacing por tenant
    └── postgres.py       # Pool asyncpg, queries de catálogo y logging
```

---

### 2. Redis — estado caliente

Redis almacena el estado más reciente de cada gateway con un **TTL de 60 segundos**.

**Formato de las keys:**
```
tenant:{tenant_id}:gateway:{gateway_slug}
```

Ejemplo: `tenant:00000000-0000-0000-0000-000000000001:gateway:gw-001`

**Valor almacenado (JSON):**
```json
{
  "available_channels": 6,
  "total_channels": 8,
  "signal_rssi": -72,
  "active_calls": 2,
  "failure_rate_5m": 0.03,
  "registered": true
}
```

**Health-check implícito por TTL**: si un monitor deja de reportar (proceso caído, red cortada, gateway desconectado), la key expira a los 60 segundos. El Core Engine no ve ninguna entry para ese gateway y lo excluye automáticamente de las decisiones. No hace falta un proceso separado de health-check — el TTL es el health-check.

**Namespacing estricto por tenant**: las keys nunca son planas (`gateway:gw-001`), siempre incluyen `tenant_id`. Esto garantiza aislamiento a nivel de estructura de datos, no solo de filtrado en código.

**Cache de API keys**: las resoluciones API key → tenant_id también se cachean en Redis por 5 minutos para no ir a Postgres en cada request.

---

### 3. Postgres — estado persistente

Almacena lo que no es efímero: catálogo de gateways, configuración, autenticación, y el histórico de decisiones.

**Tablas:**

```sql
tenants           -- Una fila por cliente
  id, name, created_at

api_keys          -- Credenciales de autenticación, vinculadas a un tenant
  id, tenant_id, key, label, created_at, revoked_at

gateways          -- Catálogo de gateways por tenant
  id, tenant_id, slug, display_name, cost_per_minute, enabled, created_at

route_decisions   -- Log de cada decisión de ruteo tomada
  id, tenant_id, call_id, gateway_slug, score, reason, decided_at
```

**`route_decisions`** es el registro histórico que permite responder: ¿cuántas llamadas pasaron por cada gateway? ¿El scoring está eligiendo bien? ¿Cuándo falló un gateway? Es la base para el dashboard de observabilidad futuro.

**Row Level Security (RLS)**: todas las tablas tienen RLS habilitado con políticas que filtran por `tenant_id`. Esto actúa como segunda red de seguridad: aunque el código de aplicación tuviera un bug de filtrado, el motor de base de datos rechaza filas fuera del tenant de la sesión.

---

### 4. Monitores (`monitors/`)

Procesos que corren **en la red del cliente**, cerca del hardware GSM. Hay un driver por marca/tipo de gateway. Su única responsabilidad es traducir el estado nativo del gateway al formato normalizado que espera el Core Engine, y reportarlo via HTTP.

**Clase base (`monitors/base.py`):**
```python
class BaseMonitor(ABC):
    async def connect(self)     # Establece sesión con el gateway (SNMP, HTTP, SSH)
    async def disconnect(self)  # Libera la sesión
    async def poll(self) -> GatewaySnapshot  # Lee el estado y lo normaliza
```

Cada driver implementa estos tres métodos. El loop de reporte (poll → POST → sleep) es genérico.

**Por qué corren en la red del cliente**: los gateways GSM exponen su management interface (panel web, SNMP, SSH) solo en red local. El monitor necesita acceso directo a esa IP. En instalaciones AsterVoIP en el cluster Proxmox propio, el monitor corre dentro del mismo LXC que ya tiene acceso al gateway vía trunk SIP — la ruta de red ya existe.

**Monitor simulado (`monitors/simulated/simulator.py`)**: para el laboratorio. Genera snapshots con valores aleatorios pero realistas (señal variable, canales ocupándose y liberándose, 95% de uptime). Permite validar todo el flujo sin hardware real.

---

### 5. Adaptadores (`adapters/`)

Procesos que corren en la infra del cliente, junto al PBX. Traducen la decisión del Core Engine a la sintaxis de cada PBX.

**Adaptador Asterisk (`adapters/asterisk/agi_route.py`)**: un script AGI (Asterisk Gateway Interface). El dialplan lo llama en el momento de la llamada saliente. El script hace un `POST /v1/route-decision` al Core Engine y escribe el resultado como variable de canal (`GWB_GATEWAY`), que el dialplan usa para construir el `Dial()`.

**Dialplan de ejemplo:**
```
exten => _X.,1,AGI(agi_route.py)
same  => n,GotoIf($["${GWB_GATEWAY}" = ""]?fallback)
same  => n,Dial(SIP/${EXTEN}@${GWB_GATEWAY})
same  => n(fallback),Dial(SIP/${EXTEN}@trunk-fallback)
```

**Timeout de 2 segundos**: si el Core Engine no responde en 2 segundos, el AGI script setea `GWB_GATEWAY` vacío y el dialplan cae al fallback (trunk configurado por defecto). La lógica de fallback vive en el dialplan, no en el adaptador.

---

## Flujo completo de una llamada

```
t=0s   Llamada saliente entra al dialplan de Asterisk

t=0s   Dialplan ejecuta AGI(agi_route.py)

t=0s   AGI script:
         POST /v1/route-decision
         Headers: X-API-Key: lab-adapter-key-001
         Body:    {"call_id": "1750800000.42"}

t=0s   Core Engine — authenticate:
         1. Busca "lab-adapter-key-001" en Redis cache
         2. Si no está: SELECT tenant_id FROM api_keys WHERE key = $1
         3. Guarda en cache por 5 min
         → tenant_id = "00000000-0000-0000-0000-000000000001"

t=0s   Core Engine — gather state:
         SELECT slug, cost_per_minute FROM gateways WHERE tenant_id = $1
         → [gw-001, gw-002, gw-003]
         
         GET tenant:...001:gateway:gw-001  → snapshot
         GET tenant:...001:gateway:gw-002  → snapshot
         GET tenant:...001:gateway:gw-003  → nil (TTL expiró → gateway offline)

t=0s   Core Engine — score:
         Puntúa gw-001 y gw-002, excluye gw-003 (sin estado)
         → gw-002: 84.3  (más barato, buena señal)
         → gw-001: 71.8

t=0s   Core Engine — log:
         INSERT INTO route_decisions (...) VALUES (tenant_id, "1750800000.42", "gw-002", 84.3, "weighted_score")

t=0s   Core Engine responde:
         {"gateway_slug": "gw-002", "score": 84.3, "reason": "weighted_score", "alternatives": [...]}

t=0s   AGI script setea variables de canal:
         GWB_GATEWAY = "gw-002"
         GWB_SCORE   = "84.3"

t=0s   Dialplan ejecuta:
         Dial(SIP/+5491155551234@gw-002)
```

El overhead total del Core Engine (auth cacheada + Redis reads + score + Postgres write) es típicamente < 10ms en producción.

---

## Scoring engine

El scoring convierte el estado de cada gateway en un número entre 0 y 100, luego aplica una suma ponderada.

**Componentes del score:**

| Componente | Peso | Fórmula | Rango entrada | Resultado |
|---|---|---|---|---|
| `available_channels` | 40% | `(disponibles / total) × 100` | 0–N canales | 0–100 |
| `signal_rssi` | 30% | `(rssi + 110) × (100/60)` | -110 a -50 dBm | 0–100 |
| `failure_rate` | 20% | `(1 - tasa_fallo) × 100` | 0.0–1.0 | 0–100 |
| `cost_per_minute` | 10% | `(1 - costo/max_costo) × 100` | $/min | 0–100 |

**Score final**: `0.40×ch + 0.30×sig + 0.20×fail + 0.10×cost`

**Exclusiones previas al scoring** (gateway descalificado directamente):
- `registered = false` → gateway no registrado en la red GSM
- `available_channels = 0` → todos los canales ocupados
- Key ausente en Redis → TTL expiró, gateway sin reportes recientes

**Ejemplo concreto:**

```
gw-001: 6/8 canales libres (-72 dBm, 3% fallos, $0.01/min)
  ch   = (6/8)×100       = 75.0
  sig  = (-72+110)×1.67  = 63.4
  fail = (1-0.03)×100    = 97.0
  cost = (1-0.01/0.012)  = 16.7  ← costo medio
  score = 0.40×75 + 0.30×63.4 + 0.20×97 + 0.10×16.7 = 72.4

gw-002: 7/8 canales libres (-65 dBm, 1% fallos, $0.008/min)
  ch   = (7/8)×100       = 87.5
  sig  = (-65+110)×1.67  = 75.1
  fail = (1-0.01)×100    = 99.0
  cost = (1-0.008/0.012) = 33.3  ← más barato, mejor score
  score = 0.40×87.5 + 0.30×75.1 + 0.20×99 + 0.10×33.3 = 82.7

→ Se elige gw-002
```

Los pesos están definidos en `ScoringWeights` en `core/app/domain/scoring.py`. En la evolución del producto, se cargarán desde la configuración de cada tenant en Postgres (sin tocar código).

---

## Multi-tenancy y aislamiento

El aislamiento entre clientes está garantizado en tres puntos independientes:

### Punto 1: El tenant se deriva de la autenticación, nunca del payload

El API key identifica al tenant. El body de la request nunca incluye `tenant_id`. Un cliente que enviara un `tenant_id` falso en el body sería ignorado — el Core Engine lo descarta y usa el tenant derivado del API key.

```python
async def resolve_tenant(api_key: str = Depends(_api_key_header)) -> str:
    # El tenant_id NUNCA viene del request body
    tenant_id = await redis_client.get_cached_api_key(api_key)
    if not tenant_id:
        tenant_id = await postgres.get_tenant_by_api_key(api_key)
    return tenant_id
```

### Punto 2: Namespacing en Redis

Las keys de Redis incluyen siempre el `tenant_id` en el prefijo. No existe la posibilidad de colisión entre gateways de distintos clientes aunque tengan el mismo slug.

```
tenant:uuid-cliente-A:gateway:gw-001   ← cliente A
tenant:uuid-cliente-B:gateway:gw-001   ← cliente B, aislado completamente
```

### Punto 3: Row Level Security en Postgres (segunda red de seguridad)

Aunque el código de aplicación tuviera un bug y olvidara filtrar por `tenant_id`, el motor de Postgres rechaza filas fuera del tenant de la sesión. Es una garantía independiente del código.

---

## Autenticación — flujo detallado

```
Request llega con: X-API-Key: abc123

1. Core busca en Redis: GET apikey:abc123
   → HIT: devuelve tenant_id directamente (evita DB, TTL=5min)

   → MISS:
     SELECT tenant_id FROM api_keys WHERE key = 'abc123' AND revoked_at IS NULL
     → Encontrado: cachea en Redis (SET apikey:abc123 <tenant_id> EX 300)
     → No encontrado: HTTP 401 "Invalid API key"
```

Esto significa que el camino caliente (API key ya vista) es un solo lookup en Redis. El camino frío (primera request del API key) hace un solo query a Postgres. Revocar un key (`revoked_at = NOW()`) tarda hasta 5 minutos en propagarse, ya que el cache Redis no se invalida proactivamente — aceptable para el piloto.

---

## Decisiones de diseño

| Decisión | Alternativa descartada | Por qué |
|---|---|---|
| Pull (adaptador pide decisión) | Push (Core envía decisiones a una cola) | Más simple, menor latencia, sin necesidad de broker. Se evalúa push cuando la escala lo justifique. |
| TTL de Redis como health-check | Proceso de health-check separado | Un proceso menos que mantener. Si el monitor para, el gateway desaparece solo. |
| Multi-tenant desde el esquema inicial | Agregar `tenant_id` después | Migrar tablas con millones de filas y Redis con millones de keys es caro. Coste cero hacerlo desde el día uno. |
| Core en infraestructura propia (GCP) | Core en infra del cliente | El valor del producto es la inteligencia centralizada. Si el core vive en el cliente, no hay producto — hay un script. |
| Monitor en red del cliente | Monitor en GCP que accede al gateway remotamente | Los gateways GSM no exponen su management interface a internet. El monitor necesita acceso local. |
| Cloudflare Tunnel (adaptadores) + Tailscale (monitores) | Un solo mecanismo para ambos | Son necesidades distintas: el adaptador hace requests HTTP síncronas desde la PBX hacia afuera (Tunnel). El monitor reporta a Redis que no debe estar expuesto a internet (Tailscale privado). |
