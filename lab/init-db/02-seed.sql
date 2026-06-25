-- Seed de laboratorio — NO usar en producción

INSERT INTO tenants (id, name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'lab-tenant');

INSERT INTO api_keys (tenant_id, key, label) VALUES
    ('00000000-0000-0000-0000-000000000001', 'lab-monitor-key-001', 'Simulated Monitor'),
    ('00000000-0000-0000-0000-000000000001', 'lab-adapter-key-001', 'Asterisk AGI Adapter');

INSERT INTO gateways (tenant_id, slug, display_name, cost_per_minute) VALUES
    ('00000000-0000-0000-0000-000000000001', 'gw-001', 'Gateway GSM 01 (Dinstar)', 0.0100),
    ('00000000-0000-0000-0000-000000000001', 'gw-002', 'Gateway GSM 02 (Dinstar)', 0.0080),
    ('00000000-0000-0000-0000-000000000001', 'gw-003', 'Gateway GSM 03 (OpenVox)', 0.0120);
