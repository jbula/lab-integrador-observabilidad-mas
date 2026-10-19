-- ════════════════════════════════════════════════════════════════════
-- init-db-analytics.sql — Esquema de data-service (base: analyticsdb)
-- Lab 4, Modulo A. Patron de base de datos por servicio.
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sales_facts (
    id         BIGSERIAL PRIMARY KEY,
    product_id VARCHAR(100)  NOT NULL,
    units_sold INTEGER       NOT NULL DEFAULT 0,
    revenue    NUMERIC(12,2) NOT NULL DEFAULT 0,
    sale_date  DATE          NOT NULL DEFAULT CURRENT_DATE,
    region     VARCHAR(50)   NOT NULL DEFAULT 'LATAM'
);

CREATE INDEX IF NOT EXISTS idx_sales_product ON sales_facts(product_id);
CREATE INDEX IF NOT EXISTS idx_sales_date    ON sales_facts(sale_date);

-- Los product_id coinciden con inventorydb y ordersdb para que la cadena
-- service-a -> service-b -> data-service resuelva de extremo a extremo.
INSERT INTO sales_facts (product_id, units_sold, revenue, region) VALUES
    ('LAPTOP-X1',   42, 54600.00, 'LATAM'),
    ('MOUSE-PRO',  310,  9300.00, 'LATAM'),
    ('KEYBOARD-MK',185, 14800.00, 'LATAM'),
    ('MONITOR-4K',  67, 26800.00, 'LATAM'),
    ('HEADSET-Z',  124,  9920.00, 'LATAM')
ON CONFLICT DO NOTHING;

-- Usuarios sinteticos para el Golden Signal de autenticacion (Modulo C).
-- Las contrasenas se almacenan como hash PBKDF2-HMAC-SHA256 (100000 rondas),
-- nunca en claro. Credenciales de laboratorio, no aptas para produccion.
CREATE TABLE IF NOT EXISTS app_users (
    username      VARCHAR(50) PRIMARY KEY,
    password_hash VARCHAR(255) NOT NULL,
    failed_count  INTEGER NOT NULL DEFAULT 0,
    last_attempt  TIMESTAMPTZ
);

-- Credenciales de laboratorio (texto en claro documentado para poder reproducir
-- los experimentos): demo/demo123, analyst/analyst123, auditor/auditor123.
-- El hash se deriva con AUTH_SALT='otel-lab-salt' y 100000 rondas.
INSERT INTO app_users (username, password_hash) VALUES
    ('demo', 'dadde71b3ec6e70afb30497b0f4b936e35edcade9fb4f11c32fc00677b03586e'),
    ('analyst', 'f07cdcc487b7da9b280f7a96456c2548d8d466629d345f43b5cf85517ce8b3d6'),
    ('auditor', '8997d700175254838dc92c88a2444ef9229dec73f51a63773cfd62ce8d7adf9d')
ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash;
