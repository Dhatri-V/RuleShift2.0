import { useState } from "react";

import Message from "../components/Message.jsx";
import { apiRequest } from "../api.js";


function AskPage({ policies }) {
  const [questionPolicyName, setQuestionPolicyName] = useState("");
  const [questionVersion, setQuestionVersion] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState("");
  const [evidence, setEvidence] = useState([]);
  const [questionMessage, setQuestionMessage] = useState({ type: "", text: "" });

  const comparablePolicies = policies.filter((policy) => policy.status !== "DRAFT");
  const questionPolicyNames = [...new Set(comparablePolicies.map((policy) => policy.name))];
  const questionVersionOptions = comparablePolicies.filter(
    (policy) => policy.name === questionPolicyName,
  );

  async function handleQuestion(event) {
    event.preventDefault();
    setAsking(true);
    setAnswer("");
    setEvidence([]);
    setQuestionMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          policy_name: questionPolicyName,
          version: questionVersion,
          question,
        }),
      });

      setAnswer(data.answer);
      setEvidence(data.evidence);
    } catch (error) {
      setQuestionMessage({ type: "error", text: error.message });
    } finally {
      setAsking(false);
    }
  }

  return (
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
            <select
              value={questionPolicyName}
              onChange={(event) => {
                setQuestionPolicyName(event.target.value);
                setQuestionVersion("");
                setAnswer("");
                setEvidence([]);
              }}
              required
            >
              <option value="">Select a policy…</option>
              {questionPolicyNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Version
            <select
              value={questionVersion}
              onChange={(event) => {
                setQuestionVersion(event.target.value);
                setAnswer("");
                setEvidence([]);
              }}
              disabled={!questionPolicyName}
              required
            >
              <option value="">
                {questionPolicyName ? "Select a version…" : "Select a policy first…"}
              </option>
              {questionVersionOptions.map((policy) => (
                <option key={policy.id} value={policy.version}>
                  {policy.version} ({policy.status})
                </option>
              ))}
            </select>
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

        <button type="submit" disabled={asking || !questionPolicyName || !questionVersion}>
          {asking ? "Finding an answer…" : "Ask RuleShift"}
        </button>
        <Message message={questionMessage} />
      </form>

      {answer && (
        <div className="answer-card" aria-live="polite">
          <span className="answer-label">Answer</span>
          <p>{answer}</p>
          {evidence.length > 0 && (
            <div className="sources">
              <span>Evidence</span>
              <div>
                {evidence.map((item, index) => (
                  <div className="evidence-item" key={`${item.version}-${item.page_number}-${index}`}>
                    <small className="evidence-meta">
                      Policy: {item.policy_name}
                    </small>
                    <small className="evidence-meta">
                      Version: {item.version}
                    </small>
                    <small className="evidence-meta">
                      Page: {item.page_number}
                    </small>
                    <small className="evidence-meta">Relevant text:</small>
                    <blockquote className="evidence-text">{item.text}</blockquote>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}


export default AskPage;