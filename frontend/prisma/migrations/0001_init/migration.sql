CREATE TABLE IF NOT EXISTS "users" (
  "user_id" TEXT PRIMARY KEY,
  "user_name" TEXT NOT NULL,
  "user_profile" TEXT NOT NULL DEFAULT '',
  "wallet_address" TEXT UNIQUE,
  "details_json" JSONB NOT NULL DEFAULT '{}'::jsonb,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "version" INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS "markets" (
  "id" SERIAL PRIMARY KEY,
  "market_type" TEXT NOT NULL,
  "type" TEXT NOT NULL,
  "price" DECIMAL(18,4) NOT NULL,
  "quantity" DECIMAL(18,4) NOT NULL,
  "finished" BOOLEAN NOT NULL DEFAULT FALSE,
  "winner" TEXT,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "version" INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS "positions" (
  "id" SERIAL PRIMARY KEY,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "market_id" INTEGER NOT NULL REFERENCES "markets"("id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "type" TEXT NOT NULL,
  "quantity" DECIMAL(18,4) NOT NULL,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "updated_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW(),
  "version" INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS "idx_positions_user_id" ON "positions" ("user_id");
CREATE INDEX IF NOT EXISTS "idx_positions_market_id" ON "positions" ("market_id");

CREATE TABLE IF NOT EXISTS "idempotency_keys" (
  "key" TEXT PRIMARY KEY,
  "endpoint" TEXT NOT NULL,
  "request_hash" TEXT,
  "response_json" JSONB NOT NULL,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_idempotency_endpoint_created_at"
  ON "idempotency_keys" ("endpoint", "created_at");
