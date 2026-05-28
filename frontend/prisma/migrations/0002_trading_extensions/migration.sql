CREATE TYPE "OrderSide" AS ENUM ('BUY', 'SELL');
CREATE TYPE "OrderType" AS ENUM ('MARKET', 'LIMIT');
CREATE TYPE "OrderStatus" AS ENUM ('PENDING', 'PARTIAL', 'FILLED', 'CANCELLED');

CREATE TABLE IF NOT EXISTS "orders" (
  "id" SERIAL PRIMARY KEY,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "market_id" INTEGER NOT NULL REFERENCES "markets"("id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "side" "OrderSide" NOT NULL,
  "order_type" "OrderType" NOT NULL,
  "status" "OrderStatus" NOT NULL DEFAULT 'PENDING',
  "requested_qty" DECIMAL(18,4) NOT NULL,
  "filled_qty" DECIMAL(18,4) NOT NULL DEFAULT 0,
  "limit_price" DECIMAL(18,4),
  "client_order_id" TEXT UNIQUE,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "version" INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS "idx_orders_user_created" ON "orders" ("user_id", "created_at");
CREATE INDEX IF NOT EXISTS "idx_orders_market_status" ON "orders" ("market_id", "status");

CREATE TABLE IF NOT EXISTS "trades" (
  "id" SERIAL PRIMARY KEY,
  "order_id" INTEGER NOT NULL REFERENCES "orders"("id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "market_id" INTEGER NOT NULL REFERENCES "markets"("id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "side" "OrderSide" NOT NULL,
  "quantity" DECIMAL(18,4) NOT NULL,
  "execution_price" DECIMAL(18,4) NOT NULL,
  "fee" DECIMAL(18,4) NOT NULL DEFAULT 0,
  "pnl" DECIMAL(18,4),
  "executed_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_trades_order_id" ON "trades" ("order_id");
CREATE INDEX IF NOT EXISTS "idx_trades_user_executed_at" ON "trades" ("user_id", "executed_at");
CREATE INDEX IF NOT EXISTS "idx_trades_market_executed_at" ON "trades" ("market_id", "executed_at");

CREATE TABLE IF NOT EXISTS "wallet_balances" (
  "id" SERIAL PRIMARY KEY,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "asset" TEXT NOT NULL,
  "available" DECIMAL(18,8) NOT NULL DEFAULT 0,
  "locked" DECIMAL(18,8) NOT NULL DEFAULT 0,
  "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  CONSTRAINT "uq_wallet_balances_user_asset" UNIQUE ("user_id", "asset")
);

CREATE INDEX IF NOT EXISTS "idx_wallet_balances_asset" ON "wallet_balances" ("asset");

CREATE TABLE IF NOT EXISTS "watchlist_items" (
  "id" SERIAL PRIMARY KEY,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE CASCADE,
  "market_id" INTEGER NOT NULL REFERENCES "markets"("id") ON UPDATE CASCADE ON DELETE CASCADE,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  CONSTRAINT "uq_watchlist_user_market" UNIQUE ("user_id", "market_id")
);
