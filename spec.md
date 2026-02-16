# spec.md  포인트 기반 온라인 빠친코(가챠형) 게임 플랫폼 (경품=디지털 전용)

> 한 줄 요약: 유저가 사이트에 돈을 **충전(입금)** 해서 **포인트**를 사고, 그 포인트로 여러 **빠친코 머신(게임 모드)** 을 플레이하며, 결과에 따라 **디지털 경품(실물/현금 아님)** 을 받는 서비스.

---

## 0) 전제 / 컴플라이언스 가드레일 (중요)

- **현금화/환전/중고거래 유도 금지**: 포인트 및 경품은 **현금/상품권/실물**로 교환 불가.
- **경품은 100% 디지털**: 프로필 꾸미기 아이템, 아바타/스킨, 뱃지, 이펙트, 테마, 시즌 패스 EXP, 머신 해금권 등.
- **청소년 접근 제한**(권장): 성인 인증(또는 최소 만 19세 체크 + 강화된 KYC 옵션).
- **책임 있는 이용**: 자가 한도(일/주/월 충전 한도), 쿨다운, 플레이타임 알림, 자가 차단.
- **확률형 아이템 고지**(권장): 각 머신의 당첨 확률/보상 테이블을 UI에서 명확히 표기 + 변경 이력 보관.
- **불법 요소 회피**: 도박/환전/현금/실물 경품으로 해석될 수 있는 문구/기능(출금, 환전, 경품 배송, 상품권 지급 등) 금지.

---

## 1) 목표 (Goals)

1. 유저가 포인트를 충전하고, 포인트로 머신을 플레이하는 **핵심 루프** 완성
2. 여러 머신(테마/확률/연출) 제공 + 시즌/이벤트 운영 가능
3. 디지털 경품 지급/인벤토리/장착 등 **리워드 시스템** 구축
4. 운영자(Admin)가 확률/보상/이벤트/유저/결제/부정행위를 관리

---

## 2) 범위 제외 (Non-Goals)

- 실물 경품 배송, 현금화/출금, P2P 거래소, 포인트 양도
- 외부 랜덤박스 실물 커머스 연동
- 성인 인증/실명 인증을 반드시 구현(단, 선택 기능으로 설계는 포함)

---

## 3) 핵심 용어

- **포인트(Point)**: 충전으로 구매하는 내부 재화 (예: 1원=1P 또는 상품별)
- **머신(Machine)**: 빠친코 게임 모드. 각 머신은 룰/확률/보상풀/연출이 다름
- **스핀(Spin)**: 1회 플레이/게임 라운드 단위 (소모 포인트 발생)
- **디지털 경품(Reward)**: 인벤토리에 들어가는 디지털 아이템/재화/권한
- **티켓(Ticket)**: 무료 플레이권(이벤트/출석 등)
- **RTP(Return to Player)**: 평균적으로 유저에게 돌아가는 가치 비율(가상의 가치 기준)

---

## 4) 사용자 플로우

### 4.1 회원가입/로그인
- 이메일/소셜 로그인(OAuth)
- 약관 동의(확률형/디지털 경품/환전불가/연령)
- (옵션) 나이 확인/성인 인증

### 4.2 충전(포인트 구매)
1. 포인트 상점  패키지 선택 (예: 5,000P / 10,000P / 30,000P)
2. 결제(카드/간편결제 등)  결제 성공 콜백
3. 지갑(Wallet)에 포인트 적립 + 영수증/내역

### 4.3 머신 선택  플레이
1. 로비에서 머신 목록(테마/소모 P/확률/대표 보상)
2. 머신 상세(확률표, 보상풀, 연출 미리보기)
3. 플레이  포인트 차감(원자적 처리)  RNG 결과  애니메이션  보상 지급

### 4.4 경품(디지털) 수령/관리
- 인벤토리에서 확인(획득일/출처/희귀도)
- 장착/사용/변환(옵션: 중복 아이템 분해  가루 재화)

---

## 5) 기능 요구사항 (MVP)

### 5.1 로비/머신
- 머신 리스트: 이름/테마/소모 포인트/대표 확률(예: 잭팟 확률)/이벤트 배지
- 머신 상세: 확률표, 보상 목록(희귀도/가치), 룰 설명, 최근 당첨(익명)

### 5.2 플레이(스핀)
- 스핀 요청 시 서버에서:
  - 유저 포인트 잔액 확인
  - 포인트 차감(트랜잭션)
  - RNG 결과 산출
  - 보상 지급(트랜잭션)
  - 결과 저장(감사 로그)
- 클라(UI)는 서버 결과를 받아 연출을 재생 (연출은 결과를 바꾸지 못함)

### 5.3 결제/충전
- 결제 생성(주문)  결제사  콜백 검증  포인트 적립
- 결제 실패/취소 처리
- 환불 정책(가능하면 미사용 포인트 범위 내 등은 법/PG 정책 따름)  
  *정확한 환불/청약철회는 국가/PG 규정에 따라 달라져서 운영 정책으로 분리*

### 5.4 인벤토리/프로필
- 인벤토리 목록/필터(희귀도, 타입)
- 장착 슬롯(예: 프로필 테두리/배경/이펙트)
- 획득 로그

### 5.5 운영자(Admin)
- 머신 CRUD (생성/수정/중지)
- 보상풀/확률 테이블 편집 + 버전 관리(변경 이력)
- 이벤트 배너/공지
- 유저 조회(지갑/플레이로그/결제내역)
- 부정행위 플래그/차단(이상 트래픽, 과도 스핀)

---

## 6) 확률/보상 설계 (추천 구조)

### 6.1 보상 타입
- Cosmetic: 스킨/테두리/프로필 배경/연출
- Currency: 가루(분해 재화), 티켓, 배지
- Access: 머신 해금권(기간/영구), 시즌 패스 EXP

### 6.2 확률 테이블(예시)
- Rarity tiers: Common / Rare / Epic / Legendary
- 1회 스핀은 등급 추첨  등급 내 아이템 추첨
- 확률은 **서버에서만** 관리/결정

### 6.3 피티(천장)/가중치(옵션)
- 연속 미당첨 시 확률 보정(천장)
- 과금 유도처럼 보일 수 있어 **설명/고지** 필수 + 단순화 권장

---

## 7) 비기능 요구사항

### 7.1 공정성/검증
- RNG: 암호학적으로 안전한 PRNG(예: secure random)
- 결과 조작 방지: 서버 서명(SpinResult에 서명값 포함) 옵션
- 감사 로그: 확률버전, 시드(노출 금지), 결과, 지급 보상 기록

### 7.2 보안
- 결제 콜백 검증(서명/토큰)
- 레이트 리밋(스핀/결제 시도)
- 리플레이 공격 방지(주문ID/nonce)
- 관리자 접근 MFA 권장

### 7.3 안정성
- 스핀 처리 원자성(포인트 차감과 보상 지급은 같은 트랜잭션)
- 중복 콜백/중복 스핀 방지(Idempotency Key)

### 7.4 성능
- 스핀 API p95 < 300ms 목표(연출은 클라에서)
- 캐시: 머신 목록/확률표(버전 기반 캐싱)

---

## 8) 데이터 모델(초안)

### 8.1 User
- id, email, createdAt, status, ageVerified(bool), banReason

### 8.2 Wallet
- userId, balancePoint, updatedAt

### 8.3 WalletTransaction
- id, userId, type(CHARGE|SPEND|REWARD|ADJUST), amount(+/-), refType, refId, createdAt

### 8.4 Machine
- id, name, theme, costPerSpin, isActive, rulesText, probabilityVersionId, createdAt

### 8.5 ProbabilityVersion
- id, machineId, versionNumber, publishedAt, notes

### 8.6 RewardPool / RewardItem
- poolId, machineId, rarity, rewardId, weight
- rewardId  RewardCatalog 참조

### 8.7 RewardCatalog
- id, type, name, rarity, metadata(json), stackable(bool)

### 8.8 Inventory
- id, userId, rewardId, qty, obtainedAt, sourceSpinId

### 8.9 Spin
- id, userId, machineId, cost, probabilityVersionId, resultRarity, resultRewardId, createdAt, clientIdempotencyKey

### 8.10 Payment
- id, userId, provider, orderId, amountKRW, pointGranted, status, createdAt, paidAt

---

## 9) API 스펙(REST 예시)

### Auth
- POST /api/auth/signup
- POST /api/auth/login
- POST /api/auth/logout

### Wallet / Shop
- GET /api/wallet
- GET /api/shop/packages
- POST /api/payments/create-order  (packageId)
- POST /api/payments/webhook/{provider}  (결제사 콜백)

### Machines
- GET /api/machines
- GET /api/machines/{id}
- POST /api/machines/{id}/spin  (idempotencyKey)

### Inventory
- GET /api/inventory?filter=...
- POST /api/inventory/equip  (slot, rewardId)

### Admin
- GET /api/admin/users/{id}
- POST /api/admin/machines
- PUT /api/admin/machines/{id}
- POST /api/admin/machines/{id}/probability/versions
- PUT /api/admin/probability/versions/{id}/publish
- POST /api/admin/users/{id}/adjust-points

---

## 10) 화면/UX (MVP)

1. 홈/로비: 머신 카드 리스트, 이벤트 배너, 내 포인트 표시
2. 머신 상세: 확률표(접기/펼치기), 보상 갤러리, 1회 플레이(XXP)
3. 플레이 연출: 구슬/릴/잭팟 애니메이션, 결과 팝업, 다시 하기
4. 상점: 포인트 패키지, 결제
5. 인벤토리: 목록/필터/장착
6. 내역: 결제 내역, 스핀 내역, 획득 내역

---

## 11) 어뷰징/부정행위 방지

- 동일 IP/계정 과도 스핀 레이트 제한
- 결제 콜백은 주문ID 단일 처리 (중복 지급 방지)
- 어드민 조작 로그(누가 언제 어떤 확률을 바꿈)
- 이상 패턴 탐지: 짧은 시간 내 대량 스핀, 특정 머신 편중, 봇 행동

---

## 12) 분석/지표 (기본)

- DAU/WAU/MAU
- ARPPU, 결제 전환율
- 머신별 스핀 수, 소모P, 지급 가치
- 희귀도별 분포(실제 vs 설정)
- 이탈 지점: 머신 상세  플레이 클릭 전환

---

## 13) MVP 마일스톤(빠르게 만들기)

### Week 1
- Auth, Wallet, Machines 읽기, Admin 기본 CRUD
### Week 2
- Spin 트랜잭션 + RNG + Inventory 지급
- 머신 상세/확률표 UI
### Week 3
- 결제 연동(샌드박스) + 포인트 충전
- 내역/로그/레이트리밋
### Week 4
- 이벤트 배너, 티켓, 간단한 책임이용(한도/알림)

---

## 14) 오픈 이슈(결정 필요)

1. 포인트 가격/패키지 구조(1원=1P? 보너스P?)
2. 보상 가치 정의(가루 환산, 중복 처리/분해)
3. 연령 확인 수준(체크박스 vs KYC)
4. 환불/청약철회 정책(법/PG 정책에 맞춘 운영 문서 필요)
5. 확률표 UI 고지 방식(머신 내/외부, 변경 공지)

---

## 15) 경품 예시 아이디어 (실물 없이도 재밌게)

- 잭팟: 레전더리 프로필 테두리 + 전용 승리 연출 + 머신 테마 배경
- 중간급: 한정 스킨/이모트/칭호(슬럼킹 같은 밈 가능)
- 하급: 가루/티켓/경험치
- 콜렉션: 세트 완성 시 추가 보너스(세트 뱃지, 배경음악)
- 시즌: 시즌마다 머신 테마/보상 교체(과거 시즌 복각은 낮은 확률)
