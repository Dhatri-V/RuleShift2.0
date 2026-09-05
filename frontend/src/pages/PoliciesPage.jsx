import Message from "../components/Message.jsx";


function PoliciesPage({ policies, policyListError, onRefresh }) {
  return (
    <section className="panel policies-panel">
      <div className="panel-heading">
        <span className="step">02</span>
        <div>
          <h3>Saved policies</h3>
          <p>Attendance rules currently stored in SQLite.</p>
        </div>
        <button className="text-button" type="button" onClick={onRefresh}>
          Refresh
        </button>
      </div>

      {policyListError ? (
        <div className="empty-state error-state">{policyListError}</div>
      ) : policies.length === 0 ? (
        <div className="empty-state">No policies saved yet.</div>
      ) : (
        <div className="policy-list">
          {policies.map((policy) => (
            <article className="policy-item" key={policy.id}>
              <div>
                <strong>{policy.name}</strong>
                <span>Version {policy.version}</span>
              </div>
              <div className="requirement">
                <strong>{policy.attendance_requirement}%</strong>
                <span>required</span>
              </div>
              <div className="status">
                <span>{policy.status}</span>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}


export default PoliciesPage;