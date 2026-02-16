import Link from "next/link";

export default function AdminPage() {
  return (
    <section>
      <h2>Admin Dashboard</h2>
      <div className="grid" style={{ marginTop: 16 }}>
        <Link className="panel" href="/admin/machines">Machines</Link>
        <Link className="panel" href="/admin/rewards">Rewards</Link>
      </div>
    </section>
  );
}

