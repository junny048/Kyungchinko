let token = "";

const $ = (id) => document.getElementById(id);
function log(msg){ $("logs").textContent = `[${new Date().toLocaleTimeString()}] ${msg}\n` + $("logs").textContent; }
function idem(){ return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(16).slice(2)}`; }

async function api(path, opt={}){
  const headers = {"Content-Type":"application/json", ...(opt.headers||{})};
  if(token) headers.Authorization = `Bearer ${token}`;
  const r = await fetch(path, {...opt, headers});
  const d = await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
  return d;
}

async function refreshWallet(){
  if(!token){ $("balance").textContent = "-"; return; }
  const d = await api("/api/wallet");
  $("balance").textContent = d.balancePoint;
}

async function loadPackages(){
  const box = $("packages"); box.innerHTML = "";
  const d = await api("/api/shop/packages", {headers:{}});
  d.items.forEach(p=>{
    const el = document.createElement("div"); el.className="item";
    el.innerHTML = `<div>${p.name}<br><small>${p.amountKRW}원 -> ${p.totalPoint}P</small></div>`;
    const btn = document.createElement("button"); btn.textContent = "충전";
    btn.onclick = async ()=>{
      if(!token) return alert("로그인 필요");
      try{
        const o = await api("/api/payments/create-order", {method:"POST", body:JSON.stringify({packageId:p.id, provider:"mockpay"})});
        await fetch("/api/payments/webhook/mockpay", {method:"POST", headers:{"Content-Type":"application/json","X-Webhook-Token":"dev-webhook-token"}, body:JSON.stringify({orderId:o.orderId, status:"PAID"})});
        await refreshWallet();
        log(`충전 완료: +${p.totalPoint}P`);
      }catch(e){ log(`충전 실패: ${e.message}`); }
    };
    el.appendChild(btn); box.appendChild(el);
  });
}

async function loadMachines(){
  const box = $("machines"); box.innerHTML = "";
  const d = await api("/api/machines", {headers:{}});
  d.items.forEach(m=>{
    const el = document.createElement("div"); el.className="item";
    el.innerHTML = `<div>${m.name}<br><small>${m.costPerSpin}P</small></div>`;
    const btn = document.createElement("button"); btn.className="alt"; btn.textContent = "스핀";
    btn.onclick = async ()=>{
      if(!token) return alert("로그인 필요");
      try{
        const r = await api(`/api/machines/${m.id}/spin`, {method:"POST", body:JSON.stringify({idempotencyKey:idem()})});
        $("result").textContent = JSON.stringify(r, null, 2);
        await refreshWallet();
        await loadInventory();
        log(`당첨: ${r.reward.name} (${r.reward.rarity})`);
      }catch(e){ log(`스핀 실패: ${e.message}`); }
    };
    el.appendChild(btn); box.appendChild(el);
  });
}

async function loadInventory(){
  const box = $("inventory"); box.innerHTML = "";
  if(!token){ box.textContent = "로그인 필요"; return; }
  const d = await api("/api/inventory");
  if(!d.items.length){ box.textContent = "아이템 없음"; return; }
  d.items.forEach(i=>{
    const el = document.createElement("div"); el.className="item";
    el.innerHTML = `<div>${i.name}<br><small>${i.rarity} / ${i.qty}개</small></div>`;
    box.appendChild(el);
  });
}

$("signup").onclick = async ()=>{
  try{
    await api("/api/auth/signup", {method:"POST", headers:{}, body:JSON.stringify({email:$("email").value.trim(), password:$("password").value})});
    log("회원가입 완료");
  }catch(e){ log(`회원가입 실패: ${e.message}`); }
};

$("login").onclick = async ()=>{
  try{
    const d = await api("/api/auth/login", {method:"POST", headers:{}, body:JSON.stringify({email:$("email").value.trim(), password:$("password").value})});
    token = d.token;
    $("status").textContent = `로그인됨: ${d.user.email}`;
    await refreshWallet();
    await loadInventory();
    log("로그인 완료");
  }catch(e){ log(`로그인 실패: ${e.message}`); }
};

$("logout").onclick = async ()=>{
  try{ if(token) await api("/api/auth/logout", {method:"POST", body:"{}"}); }catch{}
  token = "";
  $("status").textContent = "로그아웃";
  $("balance").textContent = "-";
  $("inventory").textContent = "로그인 필요";
};

(async()=>{
  await loadPackages();
  await loadMachines();
})();
