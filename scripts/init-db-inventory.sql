-- ════════════════════════════════════════════════════════════════════
-- init-db-inventory.sql — Esquema de service-b (base de datos: inventorydb)
-- Se ejecuta automáticamente al iniciar el contenedor de PostgreSQL de service-b.
-- Patrón: base de datos por servicio (service-b NO comparte DB con service-a).
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS inventory (
    product_id    VARCHAR(100) PRIMARY KEY,
    available     INTEGER NOT NULL DEFAULT 0,
    warehouse     VARCHAR(50) NOT NULL DEFAULT 'WH-MAIN',
    reserved      INTEGER NOT NULL DEFAULT 0,
    last_updated  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Datos de prueba (product_id coincide con orders.product de service-a)
INSERT INTO inventory (product_id, available, warehouse, reserved) VALUES
    ('LAPTOP-X1',   15, 'WH-BOGOTA', 2),
    ('MOUSE-PRO',   50, 'WH-MAIN',   5),
    ('KEYBOARD-MK', 30, 'WH-MAIN',   0),
    ('MONITOR-4K',   8, 'WH-BOGOTA', 1),
    ('HEADSET-Z',   22, 'WH-MAIN',   0)
ON CONFLICT (product_id) DO NOTHING;
