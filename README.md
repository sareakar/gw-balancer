# GW Balancer

Motor de decisión de ruteo de llamadas para gateways GSM. Monitorea el estado de múltiples gateways en tiempo real y decide a cuál dirigir cada llamada saliente según señal, canales disponibles, tasa de fallos y costo — en lugar del round-robin fijo que usan la mayoría de las instalaciones hoy.

Diseñado como **producto independiente y agnóstico de PBX**: el primer adaptador es para Asterisk/AsterVoIP, pero agregar soporte para FreeSWITCH o Vicidial no requiere tocar el núcleo.

---

## Documentación

| Documento | Descripción |
|---|---|
| [Arquitectura](docs/arquitectura.md) | Visión general, componentes, flujo de una llamada, scoring, multi-tenancy |
| [Contrato de API](docs/api-contract.md) | Referencia completa de endpoints con ejemplos |
| [Laboratorio local](docs/laboratorio.md) | Instrucciones paso a paso para levantar el entorno de desarrollo |

---

## Estructura del repositorio

```
gw-balancer/
├── core/               # Core Engine — FastAPI. El único componente que va a Cloud Run.
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/v1/     # Endpoints REST
│   │   ├── domain/     # Scoring engine y modelos de dominio
│   │   └── infra/      # Clientes de Redis y Postgres
│   ├── Containerfile
│   └── requirements.txt
│
├── monitors/           # Drivers por marca de gateway (corren en red del cliente)
│   ├── base.py         # Clase abstracta que todo driver debe implementar
│   └── simulated/      # Monitor falso para el laboratorio
│
├── adapters/           # Traductores por PBX
│   └── asterisk/       # Script AGI para Asterisk/AsterVoIP
│
├── docs/               # Documentación técnica
│
└── lab/                # Entorno de desarrollo local — nunca va a producción
    ├── podman-compose.yml
    ├── .env.example
    └── init-db/        # Schema SQL y seed de datos
```

---

## Quick start

```bash
cd lab
cp .env.example .env
podman-compose up
```

Ver [docs/laboratorio.md](docs/laboratorio.md) para instrucciones completas y verificación.
