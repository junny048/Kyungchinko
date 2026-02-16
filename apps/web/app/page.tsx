import Link from "next/link";

const machines = [
  { id: "sample-1", name: "Starter Machine", cost: 100, note: "균형형" },
  { id: "sample-2", name: "Neon Burst", cost: 300, note: "고위험" },
  { id: "sample-3", name: "Cherry Rush", cost: 150, note: "티켓 추천" },
];

export default function HomePage() {
  return (
    <section>
      <h1>포인트 기반 온라인 빠친코</h1>
      <p><small>현금/실물/환전 없는 100% 디지털 경품 플랫폼</small></p>
      <div className="panel" style={{ margin: "16px 0" }}>
        <b>잔액</b>
        <p>Point: 0 / Ticket: 0</p>
      </div>
      <div className="grid">
        {machines.map((m) => (
          <Link key={m.id} className="panel" href={`/machine/${m.id}`}>
            <h3>{m.name}</h3>
            <p>{m.cost} pt / spin</p>
            <small>{m.note}</small>
          </Link>
        ))}
      </div>
    </section>
  );
}

