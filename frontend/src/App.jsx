import { useEffect, useState } from "react";


const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8002";

const IMPACT_STYLES = {
  NEWLY_NON_COMPLIANT: "impact-negative",
  STILL_NON_COMPLIANT: "impact-negative",
  NEWLY_COMPLIANT: "impact-positive",
  STILL_COMPLIANT: "impact-positive",
  MORE_INFORMATION_REQUIRED: "impact-warning",
};

const DIRECTION_STYLES = {
  INCREASED: "compare-direction-increased",
  DECREASED: "compare-direction-decreased",
  UNCHANGED: "compare-direction-unchanged",
};

const STUDENT_IMPACT_STYLES = {
  NEWLY_NON_COMPLIANT: "impact-negative",
  STILL_NON_COMPLIANT: "impact-negative",
  NEWLY_COMPLIANT: "impact-positive",
  STILL_COMPLIANT: "impact-positive",
};


async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Something went wrong.");
  }

  return data;
}


function Message({ message }) {
  if (!message.text) {
    return null;
  }

  return (
    <div className={`message message-${message.type}`} role="status">
      {message.text}
    </div>
  );
}


function App() {
  const [apiOnline, setApiOnline] = useState(false);
  const [policies, setPolicies] = useState([]);
  const [policyListError, setPolicyListError] = useState("");
  const [draftRuleValues, setDraftRuleValues] = useState({});
  const [reviewingPolicyId, setReviewingPolicyId] = useState(null);
  const [reviewMessage, setReviewMessage] = useState({ type: "", text: "" });

  const [policyName, setPolicyName] = useState("");
  const [policyVersion, setPolicyVersion] = useState("");
  const [policyFile, setPolicyFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState({ type: "", text: "" });

  const [oldPolicyId, setOldPolicyId] = useState("");
  const [newPolicyId, setNewPolicyId] = useState("");
  const [comparing, setComparing] = useState(false);
  const [versionComparison, setVersionComparison] = useState(null);
  const [compareMessage, setCompareMessage] = useState({ type: "", text: "" });

  const [impactOldPolicyId, setImpactOldPolicyId] = useState("");
  const [impactNewPolicyId, setImpactNewPolicyId] = useState("");
  const [studentAttendance, setStudentAttendance] = useState("");
  const [calculatingImpact, setCalculatingImpact] = useState(false);
  const [studentImpact, setStudentImpact] = useState(null);
  const [impactMessage, setImpactMessage] = useState({ type: "", text: "" });

  const [questionPolicy, setQuestionPolicy] = useState("");
  const [questionVersion, setQuestionVersion] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState("");
  const [sources, setSources] = useState([]);
  const [questionMessage, setQuestionMessage] = useState({ type: "", text: "" });

  async function loadPolicies() {
    try {
      const data = await apiRequest("/policies");
      setPolicies(data);
      setDraftRuleValues(
        Object.fromEntries(
          data
            .filter((policy) => policy.status === "DRAFT")
            .map((policy) => [policy.id, String(policy.attendance_requirement)]),
        ),
      );
      setPolicyListError("");
      setApiOnline(true);
    } catch (error) {
      setPolicyListError(error.message);
      setApiOnline(false);
    }
  }

  useEffect(() => {
    async function checkApi() {
      try {
        await apiRequest("/");
        setApiOnline(true);
      } catch {
        setApiOnline(false);
      }
    }

    checkApi();
    loadPolicies();
  }, []);

  async function handleUpload(event) {
    event.preventDefault();

    if (!policyFile) {
      setUploadMessage({ type: "error", text: "Please select a PDF file." });
      return;
    }

    const formData = new FormData();
    formData.append("policy_name", policyName);
    formData.append("version", policyVersion);
    formData.append("file", policyFile);

    setUploading(true);
    setUploadMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/policies/upload", {
        method: "POST",
        body: formData,
      });

      setUploadMessage({
        type: "success",
        text: `${data.name} ${data.version} uploaded. Attendance requirement: ${data.attendance_requirement}%.`,
      });
      setQuestionPolicy(data.name);
      setQuestionVersion(data.version);
      setPolicyFile(null);
      setFileInputKey((currentKey) => currentKey + 1);
      await loadPolicies();
    } catch (error) {
      setUploadMessage({ type: "error", text: error.message });
    } finally {
      setUploading(false);
    }
  }

  async function handleRuleUpdate(event, policy) {
    event.preventDefault();
    setReviewingPolicyId(policy.id);
    setReviewMessage({ type: "", text: "" });

    try {
      const data = await apiRequest(`/policies/${policy.id}/rule`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          attendance_requirement: Number(draftRuleValues[policy.id]),
        }),
      });
      setReviewMessage({
        type: "success",
        text: `${data.name} ${data.version} updated to ${data.attendance_requirement}% attendance.`,
      });
      await loadPolicies();
    } catch (error) {
      setReviewMessage({ type: "error", text: error.message });
    } finally {
      setReviewingPolicyId(null);
    }
  }

  async function handleVerify(policy) {
    setReviewingPolicyId(policy.id);
    setReviewMessage({ type: "", text: "" });

    try {
      const data = await apiRequest(`/policies/${policy.id}/verify`, {
        method: "POST",
      });
      setReviewMessage({
        type: "success",
        text: `${data.name} ${data.version} verified.`,
      });
      await loadPolicies();
    } catch (error) {
      setReviewMessage({ type: "error", text: error.message });
    } finally {
      setReviewingPolicyId(null);
    }
  }

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

  async function handleQuestion(event) {
    event.preventDefault();
    setAsking(true);
    setAnswer("");
    setSources([]);
    setQuestionMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          policy_name: questionPolicy,
          version: questionVersion,
          question,
        }),
      });

      setAnswer(data.answer);
      setSources(data.sources);
    } catch (error) {
      setQuestionMessage({ type: "error", text: error.message });
    } finally {
      setAsking(false);
    }
  }

  const draftPolicies = policies.filter((policy) => policy.status === "DRAFT");

  const comparablePolicies = policies.filter((policy) => policy.status !== "DRAFT");
  const oldPolicy = comparablePolicies.find(
    (policy) => String(policy.id) === String(oldPolicyId),
  );
  const newPolicyOptions = comparablePolicies.filter(
    (policy) =>
      policy.name === oldPolicy?.name && String(policy.id) !== String(oldPolicyId),
  );

  const impactOldPolicy = comparablePolicies.find(
    (policy) => String(policy.id) === String(impactOldPolicyId),
  );
  const impactNewPolicyOptions = comparablePolicies.filter(
    (policy) =>
      policy.name === impactOldPolicy?.name && String(policy.id) !== String(impactOldPolicyId),
  );

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark" aria-hidden="true">RS</div>
        <div>
          <p className="eyebrow">Policy intelligence workspace</p>
          <h1>RuleShift <span>2.0</span></h1>
        </div>
        <div className={`api-status ${apiOnline ? "online" : "offline"}`}>
          <span aria-hidden="true" />
          API {apiOnline ? "connected" : "offline"}
        </div>
      </header>

      <main>
        <section className="intro-panel">
          <div>
            <p className="section-number">Dashboard</p>
            <h2>Understand how policy changes affect students.</h2>
            <p>
              Upload policy versions, compare attendance rules, and ask questions
              grounded in the original documents.
            </p>
          </div>
          <div className="summary-card">
            <span>Saved policies</span>
            <strong>{policies.length}</strong>
            <small>Available in SQLite</small>
          </div>
        </section>

        <div className="dashboard-grid">
          <section className="panel upload-panel">
            <div className="panel-heading">
              <span className="step">01</span>
              <div>
                <h3>Upload a policy</h3>
                <p>Extract and index attendance rules from a PDF.</p>
              </div>
            </div>

            <form onSubmit={handleUpload}>
              <div className="form-row">
                <label>
                  Policy name
                  <input
                    type="text"
                    value={policyName}
                    onChange={(event) => setPolicyName(event.target.value)}
                    placeholder="Academic Attendance Policy"
                    required
                  />
                </label>
                <label>
                  Version
                  <input
                    type="text"
                    value={policyVersion}
                    onChange={(event) => setPolicyVersion(event.target.value)}
                    placeholder="2026"
                    required
                  />
                </label>
              </div>

              <label className="file-field">
                Policy PDF
                <input
                  key={fileInputKey}
                  type="file"
                  accept="application/pdf,.pdf"
                  onChange={(event) => setPolicyFile(event.target.files[0] || null)}
                  required
                />
                <span>{policyFile ? policyFile.name : "Choose a text-based PDF"}</span>
              </label>

              <button type="submit" disabled={uploading}>
                {uploading ? "Uploading and analyzing…" : "Upload policy"}
              </button>
              <Message message={uploadMessage} />
            </form>
          </section>

          <section className="panel policies-panel">
            <div className="panel-heading">
              <span className="step">02</span>
              <div>
                <h3>Saved policies</h3>
                <p>Attendance rules currently stored in SQLite.</p>
              </div>
              <button className="text-button" type="button" onClick={loadPolicies}>
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

          <section className="panel admin-panel">
            <div className="panel-heading">
              <span className="step">AR</span>
              <div>
                <h3>Admin review</h3>
                <p>Correct extracted attendance rules before verification.</p>
              </div>
            </div>

            {draftPolicies.length === 0 ? (
              <div className="empty-state review-empty">No draft policies awaiting review.</div>
            ) : (
              <div className="review-list">
                {draftPolicies.map((policy) => {
                  const ruleValue = draftRuleValues[policy.id] ?? "";
                  const numericRuleValue = Number(ruleValue);
                  const invalidRule =
                    ruleValue === "" ||
                    !Number.isFinite(numericRuleValue) ||
                    numericRuleValue < 0 ||
                    numericRuleValue > 100;
                  const hasUnsavedRule =
                    !invalidRule && numericRuleValue !== policy.attendance_requirement;
                  const reviewBusy = reviewingPolicyId !== null;

                  return (
                    <form
                      className="review-item"
                      key={policy.id}
                      onSubmit={(event) => handleRuleUpdate(event, policy)}
                    >
                      <div className="review-policy">
                        <strong>{policy.name}</strong>
                        <span>Version {policy.version} · DRAFT</span>
                      </div>
                      <label>
                        Attendance requirement
                        <div className="number-field">
                          <input
                            type="number"
                            min="0"
                            max="100"
                            step="0.1"
                            value={ruleValue}
                            onChange={(event) =>
                              setDraftRuleValues((currentValues) => ({
                                ...currentValues,
                                [policy.id]: event.target.value,
                              }))
                            }
                            required
                          />
                          <span>%</span>
                        </div>
                      </label>
                      <div className="review-actions">
                        <button
                          type="submit"
                          disabled={reviewBusy || invalidRule || !hasUnsavedRule}
                        >
                          {reviewingPolicyId === policy.id && hasUnsavedRule
                            ? "Saving…"
                            : "Save correction"}
                        </button>
                        <button
                          className="secondary-button"
                          type="button"
                          disabled={reviewBusy || invalidRule || hasUnsavedRule}
                          onClick={() => handleVerify(policy)}
                          title={hasUnsavedRule ? "Save the correction before verifying." : ""}
                        >
                          {reviewingPolicyId === policy.id && !hasUnsavedRule
                            ? "Verifying…"
                            : "Verify"}
                        </button>
                      </div>
                    </form>
                  );
                })}
              </div>
            )}
            <Message message={reviewMessage} />
          </section>

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

          <section className="panel question-panel">
            <div className="panel-heading">
              <span className="step">04</span>
              <div>
                <h3>Ask a policy question</h3>
                <p>Answers use only the selected policy version.</p>
              </div>
            </div>

            <form onSubmit={handleQuestion}>
              <div className="form-row">
                <label>
                  Policy name
                  <input
                    type="text"
                    value={questionPolicy}
                    onChange={(event) => setQuestionPolicy(event.target.value)}
                    placeholder="Academic Attendance Policy"
                    required
                  />
                </label>
                <label>
                  Version
                  <input
                    type="text"
                    value={questionVersion}
                    onChange={(event) => setQuestionVersion(event.target.value)}
                    placeholder="2026"
                    required
                  />
                </label>
              </div>

              <label>
                Question
                <textarea
                  value={question}
                  onChange={(event) => setQuestion(event.target.value)}
                  placeholder="What attendance percentage must students maintain?"
                  rows="3"
                  required
                />
              </label>

              <button type="submit" disabled={asking}>
                {asking ? "Finding an answer…" : "Ask RuleShift"}
              </button>
              <Message message={questionMessage} />
            </form>

            {answer && (
              <div className="answer-card" aria-live="polite">
                <span className="answer-label">Answer</span>
                <p>{answer}</p>
                {sources.length > 0 && (
                  <div className="sources">
                    <span>Sources</span>
                    <div>
                      {sources.map((source, index) => (
                        <small key={`${source.version}-${source.page_number}-${index}`}>
                          {source.policy_name} · {source.version} · Page {source.page_number}
                        </small>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </section>
        </div>
      </main>

      <footer>
        <span>RuleShift 2.0</span>
        <span>Deterministic policy impact analysis</span>
      </footer>
    </div>
  );
}


export default App;
