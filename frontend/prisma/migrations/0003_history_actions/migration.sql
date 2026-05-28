CREATE TYPE "TradingActionType" AS ENUM ('BUY', 'SELL', 'MERGE', 'SPLIT', 'LIMIT');

CREATE TABLE IF NOT EXISTS "history_events" (
  "id" SERIAL PRIMARY KEY,
  "user_id" TEXT NOT NULL REFERENCES "users"("user_id") ON UPDATE CASCADE ON DELETE RESTRICT,
  "market_id" INTEGER REFERENCES "markets"("id") ON UPDATE CASCADE ON DELETE SET NULL,
  "position_id" INTEGER REFERENCES "positions"("id") ON UPDATE CASCADE ON DELETE SET NULL,
  "order_id" INTEGER REFERENCES "orders"("id") ON UPDATE CASCADE ON DELETE SET NULL,
  "trade_id" INTEGER REFERENCES "trades"("id") ON UPDATE CASCADE ON DELETE SET NULL,
  "action_type" "TradingActionType" NOT NULL,
  "quantity" DECIMAL(18,4),
  "price" DECIMAL(18,4),
  "split_ratio" DECIMAL(18,8),
  "merge_reference" TEXT,
  "details_json" JSONB NOT NULL DEFAULT '{}'::jsonb,
  "created_at" TIMESTAMPTZ(6) NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS "idx_history_events_user_created_at"
  ON "history_events" ("user_id", "created_at");
CREATE INDEX IF NOT EXISTS "idx_history_events_market_created_at"
  ON "history_events" ("market_id", "created_at");
CREATE INDEX IF NOT EXISTS "idx_history_events_action_created_at"
  ON "history_events" ("action_type", "created_at");
