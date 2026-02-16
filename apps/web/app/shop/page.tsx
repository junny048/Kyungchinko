export default function ShopPage() {
  return (
    <section className="panel">
      <h2>포인트 상점</h2>
      <p>패키지: 1,000 / 5,000(+10%) / 10,000(+15%)</p>
      <small>PG 콜백은 `/api/payments/webhook/:provider`에서 멱등 처리됩니다.</small>
    </section>
  );
}

