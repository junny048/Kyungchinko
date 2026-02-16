let token = "";

function makeIdempotencyKey() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

const $ = (id) => document.getElementById(id);
const log = (msg) => {
  const el = $("logs");
  el.textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n` + el.textContent;
};

async function api(path, opt = {}) {
  const headers = { "Content-Type": "application/json", ...(opt.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...opt, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

async function refreshWallet() {
  if (!token) { $("wallet-balance").textContent = "-"; return; }
  const w = await api("/api/wallet");
  $("wallet-balance").textContent = w.balancePoint;
}

async function loadPackages() {
  const box = $("packages");
  box.innerHTML = "";
  const d = await api("/api/shop/packages", { headers: {} });
  d.items.forEach((p) => {
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `<div>${p.name}<br><small>${p.amountKRW}원 -> ${p.totalPoint}P</small></div>`;
    const btn = document.createElement("button");
    btn.textContent = "충전";
    btn.onclick = async () => {
      if (!token) return alert("로그인 필요");
      try {
        const o = await api("/api/payments/create-order", { method: "POST", body: JSON.stringify({ packageId: p.id, provider: "mockpay" }) });
        await fetch("/api/payments/webhook/mockpay", { method: "POST", headers: { "Content-Type": "application/json", "X-Webhook-Token": "dev-webhook-token" }, body: JSON.stringify({ orderId: o.orderId, status: "PAID", payload: { ui: true } }) });
        await refreshWallet();
        log(`충전 성공: ${p.totalPoint}P`);
      } catch (e) { log(`충전 실패: ${e.message}`); }
    };
    el.appendChild(btn);
    box.appendChild(el);
  });
}

async function loadMachines() {
  const box = $("machines");
  box.innerHTML = "";
  const d = await api("/api/machines", { headers: {} });
  d.items.forEach((m) => {
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `<div>${m.name}<br><small>${m.costPerSpin}P / 잭팟 ${m.jackpotPercent ?? 0}%</small></div>`;
    const btn = document.createElement("button");
    btn.className = "alt";
    btn.textContent = "스핀";
    btn.onclick = async () => {
      if (!token) return alert("로그인 필요");
      try {
        const r = await api(`/api/machines/${m.id}/spin`, { method: "POST", body: JSON.stringify({ idempotencyKey: makeIdempotencyKey() }) });
        $("spin-result").textContent = JSON.stringify(r, null, 2);
        await refreshWallet();
        await loadInventory();
        log(`스핀 성공: ${r.reward.name} (${r.rarity})`);
      } catch (e) { log(`스핀 실패: ${e.message}`); }
    };
    el.appendChild(btn);
    box.appendChild(el);
  });
}

async function loadInventory() {
  const box = $("inventory");
  box.innerHTML = "";
  if (!token) { box.textContent = "로그인 필요"; return; }
  const d = await api("/api/inventory");
  d.items.forEach((i) => {
    const el = document.createElement("div");
    el.className = "item";
    el.innerHTML = `<div>${i.name}<br><small>${i.rarity} / 수량 ${i.qty}</small></div>`;
    box.appendChild(el);
  });
  if (!d.items.length) box.textContent = "아이템 없음";
}

$("btn-signup").onclick = async () => {
  try {
    await api("/api/auth/signup", { method: "POST", headers: {}, body: JSON.stringify({ email: $("email").value.trim(), password: $("password").value, ageVerified: true }) });
    log("회원가입 완료");
  } catch (e) { log(`회원가입 실패: ${e.message}`); }
};

$("btn-login").onclick = async () => {
  try {
    const d = await api("/api/auth/login", { method: "POST", headers: {}, body: JSON.stringify({ email: $("email").value.trim(), password: $("password").value }) });
    token = d.token;
    $("auth-status").textContent = `로그인됨: ${d.user.email}`;
    await refreshWallet();
    await loadInventory();
    log("로그인 완료");
  } catch (e) { log(`로그인 실패: ${e.message}`); }
};

$("btn-logout").onclick = async () => {
  try {
    if (token) await api("/api/auth/logout", { method: "POST", body: "{}" });
  } catch {}
  token = "";
  $("auth-status").textContent = "로그아웃";
  $("wallet-balance").textContent = "-";
  $("inventory").textContent = "로그인 필요";
};

(async () => {
  await loadPackages();
  await loadMachines();
})();

