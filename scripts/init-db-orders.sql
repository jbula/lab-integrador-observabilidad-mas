-- ════════════════════════════════════════════════════════════════════
-- init-db-orders.sql — Esquema de service-a (base de datos: ordersdb)
-- Se ejecuta automáticamente al iniciar el contenedor de PostgreSQL de service-a.
-- Patrón: base de datos por servicio (service-a NO comparte DB con service-b).
-- ════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS orders (
    id          VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    product     VARCHAR(100) NOT NULL,
    quantity    INTEGER NOT NULL DEFAULT 1,
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',
    customer_id VARCHAR(50),
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_product ON orders(product);

-- Datos de prueba (product coincide con inventory.product_id de service-b)
INSERT INTO orders (id, product, quantity, status, customer_id) VALUES
    ('ord-001', 'LAPTOP-X1',   1, 'delivered', 'cust-100'),
    ('ord-002', 'MOUSE-PRO',   2, 'pending',   'cust-101'),
    ('ord-003', 'KEYBOARD-MK', 1, 'shipped',   'cust-102'),
    ('ord-004', 'MONITOR-4K',  1, 'pending',   'cust-103'),
    ('ord-005', 'HEADSET-Z',   1, 'cancelled', 'cust-104')
ON CONFLICT (id) DO NOTHING;

-- Trigger de updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS orders_updated_at ON orders;
CREATE TRIGGER orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
