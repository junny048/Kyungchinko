export default async function PlayPage({ params }: { params: Promise<{ spinId: string }> }) {
  const { spinId } = await params;
  return (
    <section className="panel">
      <h2>Spin Result #{spinId}</h2>
      <p>서버 결정 결과를 기반으로 클라이언트 연출만 재생하는 영역입니다.</p>
    </section>
  );
}

