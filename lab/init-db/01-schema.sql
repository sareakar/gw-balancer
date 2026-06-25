-- GW Balancer — schema inicial
-- Multi-tenant desde el primer día. RLS como segunda red de seguridad.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE tenants (
    id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Plaintext en dev; en producción guardar SHA-256 del key
CREATE TABLE api_keys (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id  UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    key        TEXT NOT NULL UNIQUE,
    label      TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    revoked_at TIMESTAMPTZ
);

CREATE TABLE gateways (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    slug             TEXT NOT NULL,       -- usado en keys de Redis y respuestas API
    display_name     TEXT NOT NULL,
    cost_per_minute  NUMERIC(6,4) DEFAULT 0.0,
    enabled          BOOLEAN DEFAULT TRUE,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tenant_id, slug)
);

CREATE TABLE route_decisions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id),
    call_id      TEXT,
    gateway_slug TEXT NOT NULL,
    score        NUMERIC(6,2),
    reason       TEXT,
    decided_at   TIMESTAMPTZ DEFAULT NOW()
);

-- RLS: el motor de BD rechaza filas fuera del tenant de la sesión.
-- La app setea app.tenant_id antes de cada query; es una red de seguridad,
-- no el mecanismo principal de aislamiento.
ALTER TABLE gateways       ENABLE ROW LEVEL SECURITY;
ALTER TABLE route_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys        ENABLE ROW LEVEL SECURITY;

CREATE POLICY gateways_tenant ON gateways
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

CREATE POLICY route_decisions_tenant ON route_decisions
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

CREATE POLICY api_keys_tenant ON api_keys
    USING (tenant_id = current_setting('app.tenant_id', true)::UUID);

-- El usuario de la app hace BYPASSRLS para poder funcionar sin SET LOCAL.
-- En producción crear un rol dedicado con RLS enforced.
ALTER USER gwb BYPASSRLS;

-- Índices
CREATE INDEX ON route_decisions (tenant_id, decided_at DESC);
CREATE INDEX ON api_keys (key) WHERE revoked_at IS NULL;
