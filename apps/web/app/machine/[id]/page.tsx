import Link from "next/link";

export default async function MachineDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <section className="panel">
      <h2>Machine {id}</h2>
      <p>확률표 및 보상풀은 API `/api/machines/:id` 응답으로 렌더링하도록 확장 가능합니다.</p>
      <div style={{ display: "flex", gap: 12 }}>
        <button>포인트로 스핀</button>
        <button style={{ background: "var(--accent-2)", color: "#111" }}>티켓으로 스핀</button>
      </div>
      <p style={{ marginTop: 12 }}>
        <Link href="/play/new">최근 스핀 연출 보기</Link>
      </p>
    </section>
  );
}

