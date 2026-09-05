import { useState } from "react";

import Message from "../components/Message.jsx";
import { apiRequest } from "../api.js";

const DIRECTION_STYLES = {
  INCREASED: "compare-direction-increased",
  DECREASED: "compare-direction-decreased",
  UNCHANGED: "compare-direction-unchanged",
};


function ComparePage({ policies }) {
  const [oldPolicyId, setOldPolicyId] = useState("");
  const [newPolicyId, setNewPolicyId] = useState("");
  const [comparing, setComparing] = useState(false);
  const [versionComparison, setVersionComparison] = useState(null);
  const [compareMessage, setCompareMessage] = useState({ type: "", text: "" });

  const comparablePolicies = policies.filter((policy) => policy.status !== "DRAFT");
  const oldPolicy = comparablePolicies.find(
    (policy) => String(policy.id) === String(oldPolicyId),
  );
  const newPolicyOptions = comparablePolicies.filter(
    (policy) =>
      policy.name === oldPolicy?.name && String(policy.id) !== String(oldPolicyId),
  );

  async function handleCompare(event) {
    event.preventDefault();
    setComparing(true);
    setVersionComparison(null);
    setCompareMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/compare-versions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          old_policy_id: Number(oldPolicyId),
          new_policy_id: Number(newPolicyId),
        }),
      });

      setVersionComparison(data);
    } catch (error) {
      setCompareMessage({ type: "error", text: error.message });
    } finally {
      setComparing(false);
    }
  }

  return (
    <section className="panel compare-panel">
      <div className="panel-heading">
        <span className="step">03</span>
        <div>
          <h3>Compare policy versions</h3>
          <p>Compare verified attendance rules stored in SQLite.</p>
        </div>
      </div>

      <form onSubmit={handleCompare}>
        <div className="form-row">
          <label>
            Old policy version
            <select
              value={oldPolicyId}
              onChange={(event) => {
                setOldPolicyId(event.target.value);
                setNewPolicyId("");
                setVersionComparison(null);
              }}
              required
            >
              <option value="">Select a version…</option>
              {comparablePolicies.map((policy) => (
                <option key={policy.id} value={policy.id}>
                  {policy.name} · {policy.version} ({policy.status})
                </option>
              ))}
            </select>
          </label>
          <label>
            New policy version
            <select
              value={newPolicyId}
              onChange={(event) => {
                setNewPolicyId(event.target.value);
                setVersionComparison(null);
              }}
              disabled={!oldPolicy}
              required
            >
              <option value="">
                {oldPolicy ? "Select a newer version…" : "Select old version first…"}
              </option>
              {newPolicyOptions.map((policy) => (
                <option key={policy.id} value={policy.id}>
                  {policy.version} ({policy.status}) — {policy.attendance_requirement}%
                </option>
              ))}
            </select>
          </label>
        </div>

        <button type="submit" disabled={comparing || !oldPolicy || !newPolicyId}>
          {comparing ? "Comparing…" : "Compare versions"}
        </button>
        <Message message={compareMessage} />
      </form>

      {versionComparison && (
        <div
          className={`version-compare-result ${DIRECTION_STYLES[versionComparison.direction] || ""}`}
          aria-live="polite"
        >
          {versionComparison.direction === "UNCHANGED" ? (
            <>
              <span>Requirement unchanged</span>
              <div className="compare-numbers">
                <strong>{versionComparison.old_policy.attendance_requirement}%</strong>
                <span className="compare-arrow">→</span>
                <strong>{versionComparison.new_policy.attendance_requirement}%</strong>
                <span className="compare-delta">(0%)</span>
              </div>
            </>
          ) : (
            <>
              <span>
                Requirement {versionComparison.direction === "INCREASED" ? "increased" : "decreased"}
              </span>
              <div className="compare-numbers">
                <strong>{versionComparison.old_policy.attendance_requirement}%</strong>
                <span className="compare-arrow">→</span>
                <strong>{versionComparison.new_policy.attendance_requirement}%</strong>
                <span className="compare-delta">
                  ({versionComparison.difference > 0 ? "+" : ""}{versionComparison.difference}%)
                </span>
              </div>
            </>
          )}
          <div className="compare-policy-names">
            <span>
              {versionComparison.old_policy.version} ({versionComparison.old_policy.status})
            </span>
            <span className="compare-arrow">→</span>
            <span>
              {versionComparison.new_policy.version} ({versionComparison.new_policy.status})
            </span>
          </div>
          <code>{versionComparison.direction}</code>
        </div>
      )}
    </section>
  );
}


export default ComparePage;