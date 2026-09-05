import { useState } from "react";

import Message from "../components/Message.jsx";
import { apiRequest } from "../api.js";

const STUDENT_IMPACT_STYLES = {
  NEWLY_NON_COMPLIANT: "impact-negative",
  STILL_NON_COMPLIANT: "impact-negative",
  NEWLY_COMPLIANT: "impact-positive",
  STILL_COMPLIANT: "impact-positive",
};


function ImpactPage({ policies }) {
  const [impactOldPolicyId, setImpactOldPolicyId] = useState("");
  const [impactNewPolicyId, setImpactNewPolicyId] = useState("");
  const [studentAttendance, setStudentAttendance] = useState("");
  const [calculatingImpact, setCalculatingImpact] = useState(false);
  const [studentImpact, setStudentImpact] = useState(null);
  const [impactMessage, setImpactMessage] = useState({ type: "", text: "" });

  const comparablePolicies = policies.filter((policy) => policy.status !== "DRAFT");
  const impactOldPolicy = comparablePolicies.find(
    (policy) => String(policy.id) === String(impactOldPolicyId),
  );
  const impactNewPolicyOptions = comparablePolicies.filter(
    (policy) =>
      policy.name === impactOldPolicy?.name && String(policy.id) !== String(impactOldPolicyId),
  );

  async function handleStudentImpact(event) {
    event.preventDefault();
    setCalculatingImpact(true);
    setStudentImpact(null);
    setImpactMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/student-impact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          old_policy_id: Number(impactOldPolicyId),
          new_policy_id: Number(impactNewPolicyId),
          attendance: Number(studentAttendance),
        }),
      });

      setStudentImpact(data);
    } catch (error) {
      setImpactMessage({ type: "error", text: error.message });
    } finally {
      setCalculatingImpact(false);
    }
  }

  return (
    <section className="panel impact-panel">
      <div className="panel-heading">
        <span className="step">03B</span>
        <div>
          <h3>Student impact</h3>
          <p>Calculate how a policy change affects a student.</p>
        </div>
      </div>

      <form onSubmit={handleStudentImpact}>
        <div className="form-row three-columns">
          <label>
            Old policy version
            <select
              value={impactOldPolicyId}
              onChange={(event) => {
                setImpactOldPolicyId(event.target.value);
                setImpactNewPolicyId("");
                setStudentImpact(null);
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
              value={impactNewPolicyId}
              onChange={(event) => {
                setImpactNewPolicyId(event.target.value);
                setStudentImpact(null);
              }}
              disabled={!impactOldPolicy}
              required
            >
              <option value="">
                {impactOldPolicy ? "Select a newer version…" : "Select old version first…"}
              </option>
              {impactNewPolicyOptions.map((policy) => (
                <option key={policy.id} value={policy.id}>
                  {policy.version} ({policy.status}) — {policy.attendance_requirement}%
                </option>
              ))}
            </select>
          </label>
          <label>
            Student attendance
            <div className="number-field">
              <input
                type="number"
                min="0"
                max="100"
                step="0.1"
                value={studentAttendance}
                onChange={(event) => {
                  setStudentAttendance(event.target.value);
                  setStudentImpact(null);
                }}
                placeholder="80"
                required
              />
              <span>%</span>
            </div>
          </label>
        </div>

        <button
          type="submit"
          disabled={calculatingImpact || !impactOldPolicy || !impactNewPolicyId || !studentAttendance}
        >
          {calculatingImpact ? "Calculating…" : "Calculate impact"}
        </button>
        <Message message={impactMessage} />
      </form>

      {studentImpact && (
        <div
          className={`student-impact-result ${STUDENT_IMPACT_STYLES[studentImpact.impact] || ""}`}
          aria-live="polite"
        >
          <div className="impact-heading">
            <span>Student attendance</span>
            <strong>{studentImpact.attendance}%</strong>
          </div>
          <div className="impact-rows">
            <div className="impact-row">
              <span className="impact-version">
                {studentImpact.old_policy.version} requirement
              </span>
              <strong>{studentImpact.old_policy.attendance_requirement}%</strong>
              <span className="impact-pass-fail">{studentImpact.old_policy.result}</span>
            </div>
            <div className="impact-row">
              <span className="impact-version">
                {studentImpact.new_policy.version} requirement
              </span>
              <strong>{studentImpact.new_policy.attendance_requirement}%</strong>
              <span className="impact-pass-fail">{studentImpact.new_policy.result}</span>
            </div>
          </div>
          <div className="impact-summary">
            <span>Impact</span>
            <strong>{studentImpact.impact.replaceAll("_", " ")}</strong>
            <code>{studentImpact.impact}</code>
          </div>
        </div>
      )}
    </section>
  );
}


export default ImpactPage;