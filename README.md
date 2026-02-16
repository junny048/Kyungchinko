# Kyungchinko MVP API

`spec.md` 기반 Week 1~4 MVP 백엔드 구현입니다.

## Run

```bash
python app/server.py
```

기본 주소: `http://127.0.0.1:8000`

환경 변수:
- `ADMIN_KEY` (기본값: `dev-admin-key`)
- `WEBHOOK_TOKEN` (기본값: `dev-webhook-token`)
- `SPIN_SIGNING_KEY` (기본값: `dev-spin-signing-key`)
- `DB_PATH` (기본값: `app.db`)
- `HOST` (기본값: `127.0.0.1`)
- `PORT` (기본값: `8000`)

## Implemented APIs

### Auth
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout`

### Wallet / Shop / Payments
- `GET /api/wallet`
- `GET /api/shop/packages`
- `POST /api/payments/create-order`
- `POST /api/payments/webhook/{provider}`

### Machines / Spin
- `GET /api/machines`
- `GET /api/machines/{id}`
- `POST /api/machines/{id}/spin`

### Inventory / Profile
- `GET /api/inventory?rarity=&type=`
- `POST /api/inventory/equip`
- `GET /api/me/history?type=all|payments|spins|rewards`

### Responsible Play
- `GET /api/me/responsible-limit`
- `POST /api/me/responsible-limit`
- `POST /api/me/self-exclusion`

### Events
- `GET /api/events`

### Admin
- `GET /api/admin/users/{id}`
- `POST /api/admin/machines`
- `PUT /api/admin/machines/{id}`
- `POST /api/admin/machines/{id}/probability/versions`
- `PUT /api/admin/probability/versions/{id}/publish`
- `POST /api/admin/users/{id}/adjust-points`
- `POST /api/admin/events`

## Notes

- 스핀은 서버 RNG + 트랜잭션으로 처리되고, `idempotencyKey`를 지원합니다.
- 결제 웹훅은 `X-Webhook-Token`으로 검증합니다.
- 경품은 디지털 전용으로 인벤토리에 지급되며, 장착 슬롯을 지원합니다.
- 레이트리밋(스핀/결제요청)과 책임이용 한도/쿨다운/자가차단(기간)을 포함합니다.
