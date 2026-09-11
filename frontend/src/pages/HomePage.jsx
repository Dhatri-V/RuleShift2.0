function HomePage({ policies }) {
  return (
    <section className="intro-panel">
      <div>
        <p className="section-number">Dashboard</p>
        <h2>Understand how policy changes affect students.</h2>
        <p>
          Browse policies, compare attendance rules, check student impact, and ask questions
          grounded in the original documents.
        </p>
      </div>
      <div className="summary-card">
        <span>Saved policies</span>
        <strong>{policies.length}</strong>
        <small>Available in SQLite</small>
      </div>
    </section>
  );
}


export default HomePage;