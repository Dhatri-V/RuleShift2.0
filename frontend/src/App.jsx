import { useEffect, useState } from "react";


const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

const IMPACT_STYLES = {
  NEWLY_NON_COMPLIANT: "impact-negative",
  STILL_NON_COMPLIANT: "impact-negative",
  NEWLY_COMPLIANT: "impact-positive",
  STILL_COMPLIANT: "impact-positive",
  MORE_INFORMATION_REQUIRED: "impact-warning",
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

  const [policyName, setPolicyName] = useState("");
  const [policyVersion, setPolicyVersion] = useState("");
  const [policyFile, setPolicyFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState({ type: "", text: "" });

  const [attendance, setAttendance] = useState("");
  const [oldRequirement, setOldRequirement] = useState("");
  const [newRequirement, setNewRequirement] = useState("");
  const [comparing, setComparing] = useState(false);
  const [impactResult, setImpactResult] = useState("");
  const [compareMessage, setCompareMessage] = useState({ type: "", text: "" });

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

  async function handleCompare(event) {
    event.preventDefault();
    setComparing(true);
    setImpactResult("");
    setCompareMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/compare", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          attendance: attendance === "" ? null : Number(attendance),
          old_attendance_requirement: Number(oldRequirement),
          new_attendance_requirement: Number(newRequirement),
        }),
      });

      setImpactResult(data.result);
    } catch (error) {
      setCompareMessage({ type: "error", text: error.message });
    } finally {
      setComparing(false);
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
                      <span>Policy #{policy.id}</span>
                    </div>
                    <div className="requirement">
                      <strong>{policy.attendance_requirement}%</strong>
                      <span>required</span>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="panel compare-panel">
            <div className="panel-heading">
              <span className="step">03</span>
              <div>
                <h3>Compare rules</h3>
                <p>Calculate student impact with deterministic logic.</p>
              </div>
            </div>

            <form onSubmit={handleCompare}>
              <div className="form-row three-columns">
                <label>
                  Student attendance
                  <div className="number-field">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={attendance}
                      onChange={(event) => setAttendance(event.target.value)}
                      placeholder="80"
                    />
                    <span>%</span>
                  </div>
                </label>
                <label>
                  Old requirement
                  <div className="number-field">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={oldRequirement}
                      onChange={(event) => setOldRequirement(event.target.value)}
                      placeholder="75"
                      required
                    />
                    <span>%</span>
                  </div>
                </label>
                <label>
                  New requirement
                  <div className="number-field">
                    <input
                      type="number"
                      min="0"
                      max="100"
                      step="0.1"
                      value={newRequirement}
                      onChange={(event) => setNewRequirement(event.target.value)}
                      placeholder="85"
                      required
                    />
                    <span>%</span>
                  </div>
                </label>
              </div>

              <button type="submit" disabled={comparing}>
                {comparing ? "Comparing…" : "Compare impact"}
              </button>
              <Message message={compareMessage} />
            </form>

            {impactResult && (
              <div
                className={`impact-result ${IMPACT_STYLES[impactResult] || ""}`}
                aria-live="polite"
              >
                <span>Impact result</span>
                <strong>{impactResult.replaceAll("_", " ")}</strong>
                <code>{impactResult}</code>
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
