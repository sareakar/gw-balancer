# GW Balancer — Resumen Ejecutivo del Proyecto

## Qué es

Motor de decisión de enrutamiento de llamadas para gateways GSM, desarrollado como **producto independiente** (no como script ad-hoc de un cliente). Monitorea el estado de múltiples gateways GSM (canales disponibles, nivel de señal, tasa de fallos, estado de registro) y decide a cuál gateway dirigir cada llamada saliente según criterios configurables.

Diseñado desde el día uno para ser **agnóstico de PBX**: el primer adaptador es para AsterVoIP/Asterisk, pero la arquitectura permite agregar adaptadores para FreeSWITCH, Vicidial u otras plataformas sin tocar el núcleo.

## Por qué existe

Las instalaciones con varios gateways GSM hoy distribuyen llamadas con lógica básica (round-robin fijo, orden de trunk) sin considerar el estado real de cada gateway en el momento de la llamada. Esto genera llamadas fallidas o de mala calidad cuando un gateway tiene poca señal, pocos canales libres, o está fallando, mientras otro gateway disponible queda sin usar.

## Caso de uso piloto

Cliente con instalación AsterVoIP en el cluster Proxmox propio, con discador y múltiples gateways GSM (a relevar — no es el cliente colombiano mencionado en trabajo previo). Funciona como validación del producto, pero el desarrollo vive **fuera** de la infraestructura del cliente desde el día uno — el cliente es un *consumidor* del servicio, no su *host*.

## Arquitectura (3 capas)

```
[Gateways GSM] ← Monitores (drivers por marca) → Redis (estado, TTL)
                                                        ↓
                                              Core Engine (FastAPI)
                                              scoring + decisión
                                                        ↑
[Dialplan AsterVoIP] ← Adaptador (AGI) ← HTTP ←────────┘
```

| Componente | Responsabilidad | Dónde corre |
|---|---|---|
| **Core Engine** | Recibe estado, aplica reglas de scoring, devuelve decisión de ruteo | Cloud Run (GCP) |
| **Redis** | Estado "caliente" de cada gateway, con expiración automática (TTL) como health-check implícito | VM en GCP |
| **Postgres** | Catálogo de gateways, configuración de estrategias, histórico/reportes | VM en GCP |
| **Monitores** | Un driver por marca/tipo de gateway, traducen su estado nativo a formato común | Red del cliente (cerca del hardware GSM) |
| **Adaptadores** | Traducen la decisión del core a la sintaxis de cada PBX (AGI para Asterisk) | Infra del cliente, junto al PBX |

**Principio de diseño**: el core nunca sabe de sintaxis de PBX ni de protocolos de gateways específicos. Solo recibe estado normalizado y devuelve un `gateway_id` con su razón. Toda la traducción vive en los bordes (monitores y adaptadores), que son intercambiables.

## Decisiones tomadas

- **Pull sobre push**: los adaptadores piden decisión vía REST por cada llamada (`POST /v1/route-decision`); push a colas queda para cuando la escala lo justifique.
- **Multi-tenant desde el esquema inicial**: aunque el piloto tiene un solo cliente, todas las tablas incluyen `tenant_id` desde el primer día.
- **Separación física, no solo lógica**: Core Engine en infraestructura propia (GCP), nunca en la del cliente.
- **Exposición pública vía Cloudflare Tunnel** (Core Engine en Cloud Run); **acceso privado vía Tailscale** (monitores del cliente reportando a Redis/Postgres). Dos mecanismos para dos necesidades distintas — nunca Redis expuesto directamente a internet.
- **Scoring configurable por YAML/config**, no hardcodeado — permite ajustar pesos (canales libres, señal, tasa de fallo, costo) sin tocar código.

## Stack técnico

- **Core**: Python + FastAPI + Pydantic
- **Estado caliente**: Redis (TTL por gateway)
- **Estado persistente**: Postgres (catálogo, config, histórico)
- **Contenedores**: Podman (laboratorio local) → Cloud Run (producción, mismo Containerfile)
- **Red privada**: Tailscale (monitor ↔ Redis/Postgres)
- **Red pública**: Cloudflare Tunnel (adaptador del cliente ↔ Core Engine en Cloud Run)
- **Laboratorio**: notebook local con podman-compose, antes de migrar a GCP

## Estructura de proyecto

```
gw-balancer/
├── core/          # FastAPI — único componente que va a Cloud Run
├── monitors/      # Drivers por marca de gateway (corren en red del cliente)
├── adapters/       # Traductores por PBX (asterisk/, freeswitch/...)
├── docs/          # glosario, contrato de API, arquitectura
└── lab/           # podman-compose para desarrollo local, nunca a producción
```

## Vocabulario del dominio

- **Gateway**: unidad física/lógica con N canales (un Dinstar, un trunk SIP, un chan_dongle)
- **Channel/Port**: unidad mínima dentro de un gateway
- **Route Request**: pedido del adaptador al core ("necesito un gateway")
- **Route Decision**: respuesta del core (gateway elegido + razón + score)
- **Health Snapshot**: estado normalizado de un gateway en un momento dado

## Multi-tenancy y aislamiento (decisiones de diseño)

Los clientes son instalaciones AsterVoIP en el cluster Proxmox propio; los gateways GSM físicos viven en infraestructura del cliente, pero **ya están registrados/expuestos por IP hacia el LXC del AsterVoIP** (hoy se usan para señalización SIP/troncal). Esto significa que la ruta de red que el monitor necesita **ya existe** — no hace falta Tailscale ni VPN nueva del lado del cliente; el monitor corre como un proceso más dentro del mismo LXC que ya administramos.

```
[LXC AsterVoIP - Proxmox propio]
  ├── Asterisk (ya pega al GW por IP, vía trunk/peer)
  ├── Monitor (nuevo) → misma IP del GW, por SNMP/HTTP de management
  │     └── reporta estado → Redis (GCP, vía Tailscale o Cloudflare Tunnel)
  └── Adaptador AGI (nuevo) → consulta Core Engine (GCP) → decide gateway
```

**Aislamiento estricto por tenant, garantizado en 3 puntos (no solo "filtrar por tenant_id"):**

1. **El tenant se deriva de la autenticación, nunca del payload** — cada cliente tiene su API key, asociada a exactamente un `tenant_id` en Postgres. El Core Engine ignora cualquier `tenant_id` que venga en el body de la request.
2. **Namespacing en Redis por tenant** — keys con formato `tenant:<tenant_id>:gateway:<gateway_id>`, nunca `gateway:<id>` plano, para evitar colisiones y limitar el alcance de cualquier bug de filtrado.
3. **Row Level Security (RLS) en Postgres** — el motor de base de datos rechaza filas fuera del tenant de la sesión, como segunda red de seguridad aunque el código de aplicación tuviera un bug.

**Observabilidad en dos niveles** (mismo set de tablas/métricas, distinto filtro de autorización — nunca dos sistemas separados):
- **Por cliente**: estado de sus propios gateways, histórico de decisiones, métricas de señal/canales/fallos — todo filtrado por su `tenant_id`.
- **Admin (cross-tenant)**: lo mismo para todos los tenants, más salud del Core Engine (latencia, errores, uptime) y alertas operativas (ej. "tenant X no reporta estado hace 5 min").
- Implementación sugerida a futuro: Prometheus (métricas con label `tenant_id`) + Grafana (dashboards parametrizados por tenant). No se construye en el piloto, pero las métricas deben incluir el label desde el día uno para evitar migrar datos después.

## Roadmap de implementación

1. **Laboratorio local** (notebook, podman-compose): core + Redis + Postgres + monitor simulado (datos falsos) para validar el flujo sin depender de hardware real
2. **Diseño de aislamiento multi-tenant**: esquema Postgres con `tenant_id` + RLS, namespacing de keys en Redis, autenticación por API key → tenant — antes de escribir el primer driver real, para que quede incorporado desde el primer schema
3. **Relevamiento del gateway del cliente piloto** (a definir, no es el colombiano): marca/modelo, tipo de registro en Asterisk (PJSIP/SIP/IAX2/chan_dongle), interfaz de management disponible (panel web, SNMP, API REST, SSH/CLI), datos que expone por canal (registro de SIM, RSSI, libre/ocupado, fallos), credenciales de acceso
4. **Primer driver real**: el monitor para el gateway relevado en el paso 3, corriendo dentro del LXC del AsterVoIP de ese cliente (reusa la ruta de red ya existente)
5. **Primer adaptador**: script AGI + snippet de dialplan para AsterVoIP
6. **Prueba end-to-end** contra una instalación AsterVoIP de prueba (no la de producción del cliente)
7. **Migración a Cloud Run**: mismo Containerfile del core, Redis/Postgres a VM chica en GCP
8. **Exposición**: Cloudflare Tunnel (público, hacia adaptadores de clientes) + Tailscale (privado, monitores ↔ DB)
9. **Piloto en producción** con el cliente definido en el paso 3
10. **Generalización**: segundo driver de gateway y/o segundo adaptador de PBX, para validar que el core no necesitó cambios; evaluar si corresponde construir dashboards de observabilidad por cliente/admin

## Pendiente de definir

- Modelo de negocio: self-hosted vs SaaS operado por vos
- Licenciamiento: core abierto + adaptadores pagos, o todo cerrado
- Alcance final: ¿el producto incluye lógica de dialer/ACD o se queda puramente como decision engine?
