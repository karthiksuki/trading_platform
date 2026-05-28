# Frontend Setup (Vite + Prisma + Supabase)

## Prisma + Supabase

1. Copy env template:

```bash
cp .env.local.example .env.local
```

2. Put your Supabase DB password in:
- `DATABASE_URL` (port `6543`, `pgbouncer=true`)
- `DIRECT_URL` (port `5432`, migrations)

3. Generate Prisma client:

```bash
npm run prisma:generate
```

4. Apply schema to Supabase:

```bash
npm run prisma:migrate -- --name init
```

or

```bash
npm run prisma:push
```

## Models Created

- `users`
- `markets`
- `positions`
- `idempotency_keys`
