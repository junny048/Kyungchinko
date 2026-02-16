# Kyungchinko MVP API

`spec.md` 기반 Week 1 범위(Auth/Wallet/Machines/Admin CRUD) 최소 구현입니다.

## Run

```bash
python app/server.py
```

기본 주소: `http://127.0.0.1:8000`

환경 변수:
- `ADMIN_KEY` (기본값: `dev-admin-key`)
- `DB_PATH` (기본값: `app.db`)
- `HOST` (기본값: `127.0.0.1`)
- `PORT` (기본값: `8000`)

## Implemented Endpoints

### Health
- `GET /health`

### Auth
- `POST /api/auth/signup`
- `POST /api/auth/login`
- `POST /api/auth/logout` (Bearer token 필요)

### Wallet
- `GET /api/wallet` (Bearer token 필요)

### Machines
- `GET /api/machines`
- `GET /api/machines/{id}`

### Admin
- `GET /api/admin/users/{id}` (`X-Admin-Key` 필요)
- `POST /api/admin/machines` (`X-Admin-Key` 필요)
- `PUT /api/admin/machines/{id}` (`X-Admin-Key` 필요)

## Quick Test (PowerShell)

```powershell
# 1) 회원가입
$signup = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/signup -ContentType 'application/json' -Body '{"email":"test@example.com","password":"password123","ageVerified":true}'

# 2) 로그인
$login = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/auth/login -ContentType 'application/json' -Body '{"email":"test@example.com","password":"password123"}'
$token = $login.token

# 3) 지갑 조회
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/wallet -Headers @{ Authorization = "Bearer $token" }

# 4) 머신 조회
Invoke-RestMethod -Method Get -Uri http://127.0.0.1:8000/api/machines
```

## Notes

- 포인트 충전/결제, 스핀 트랜잭션, 인벤토리 지급은 다음 단계(Week 2~3) 범위입니다.
- 이 구현은 MVP 프로토타입용이며, 운영환경에서는 비밀번호 해시 전략/세션/보안 설정을 강화해야 합니다.
