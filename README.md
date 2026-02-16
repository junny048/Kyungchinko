# Point Pachinko Platform (Single Release)

## Monorepo
- `apps/api`: Fastify + Prisma + PostgreSQL + Redis
- `apps/web`: Next.js App Router
- `packages/shared`: shared types

## Compliance Guardrails
- No cash-out, no real-world goods, no gift cards
- Rewards are digital only
- Probability table/version is exposed and auditable
- Responsible usage controls are planned in settings flow

## Quick Start
1. Copy `apps/api/.env.example` to `apps/api/.env`
2. Run infrastructure: `docker compose up -d postgres redis`
3. Install deps: `npm install`
4. Generate client/migrate/seed:
   - `npm run prisma:generate`
   - `npm run prisma:migrate`
   - `npm run prisma:seed`
5. Start API: `npm run dev -w apps/api`
6. Start Web: `npm run dev -w apps/web`

## Core Implemented APIs
- Auth: `/api/auth/*`
- Wallet/Ledger: `/api/wallet`, `/api/ledger`
- Shop/Payment: `/api/shop/packages`, `/api/payments/create-order`, `/api/payments/webhook/:provider`
- Machines: `/api/machines`, `/api/machines/:id`, `/api/machines/:id/spin`
- Inventory/Equip: `/api/inventory`, `/api/inventory/equip`, `/api/profile/equip`
- Events: `/api/events/daily-checkin`, `/api/events/status`
- Admin: machine/probability/reward/user/adjust endpoints

## Spin Transaction Guarantees
- Idempotency key unique per user: `(userId, idempotencyKey)`
- Atomic point/ticket deduction + reward grant + ledger + spin log
- RNG is server-side only (`crypto.randomInt`)
- Spin stores `probabilityVersionId` for post-audit

## Seed Accounts
- `admin@example.com` / `password`
- `user@example.com` / `password`

