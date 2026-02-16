# Kyungchinko (Clean Rebuild)

## Run

```bash
python app/server.py
```

## Open

- UI: `http://127.0.0.1:8000/`
- Health: `http://127.0.0.1:8000/health`

## Included

- Auth: signup/login/logout
- Wallet
- Shop packages + create-order + webhook(PAID)
- Machine list + spin
- Inventory
- Static web UI

## Env

- `ADMIN_KEY` (for future admin APIs)
- `WEBHOOK_TOKEN` (default: `dev-webhook-token`)
- `SPIN_SIGNING_KEY`
- `DB_PATH`, `HOST`, `PORT`
