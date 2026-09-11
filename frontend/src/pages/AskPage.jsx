import { useState } from "react";

import Message from "../components/Message.jsx";
import { apiRequest } from "../api.js";


function conciseAnswer(answer) {
  const normalized = answer.trim().replace(/\s+/g, " ");
  const sentences = normalized.match(/[^.!?]+(?:[.!?]+(?=\s|$)|$)/g) || [normalized];
  return sentences.slice(0, 2).map((sentence) => sentence.trim()).join(" ");
}


function evidenceScore(item, question, answer) {
  if (!/\battendance\b/i.test(question)) return 0;

  const text = item.text || "";
  let score = 0;
  if (/\bminimum attendance requirement\s+(?:is|shall be)\s+\d{1,3}%/i.test(text)) score += 100;
  if (/\b(?:must|shall|required to)\s+maintain\b[^.]{0,100}\b\d{1,3}%/i.test(text)) score += 80;
  if (/\b(?:section\s+\d+\s*\/\s*)?attendance\b/i.test(text)) score += 20;

  const answerPercentages = answer.match(/\b\d{1,3}%/g) || [];
  if (answerPercentages.some((percentage) => text.includes(percentage))) score += 10;

  if (!score && /\b(?:condonation|correction|approved activit)/i.test(text)) score -= 10;
  return score;
}


function orderedEvidence(evidence, question, answer) {
  return evidence
    .map((item, index) => ({ item, index, score: evidenceScore(item, question, answer) }))
    .sort((left, right) => right.score - left.score || left.index - right.index)
    .map(({ item }) => item);
}


function titleCase(value) {
  if (value !== value.toUpperCase()) return value;
  return value.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
}


function sourceLabel(source) {
  const text = source.text || "";
  const sectionNumber = text.match(/(?:^|\n)\s*(\d+(?:\.\d+)+)\s+[^\n]+/m)?.[1];
  const sectionTitle = text.match(/(?:^|\n)\s*SECTION\s+\d+\s*\/\s*([^\n]+)/im)?.[1]?.trim();
  const section = sectionNumber
    ? `Section ${sectionNumber}${sectionTitle ? ` — ${titleCase(sectionTitle)}` : ""}`
    : source.policy_name;
  return `Source: ${section}, ${source.version} policy, page ${source.page_number}`;
}


function AskPage({ policies }) {
  const [questionPolicyName, setQuestionPolicyName] = useState("");
  const [questionVersion, setQuestionVersion] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answer, setAnswer] = useState("");
  const [evidence, setEvidence] = useState([]);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [answeredQuestion, setAnsweredQuestion] = useState("");
  const [questionMessage, setQuestionMessage] = useState({ type: "", text: "" });

  const comparablePolicies = policies.filter((policy) => policy.status !== "DRAFT");
  const questionPolicyNames = [...new Set(comparablePolicies.map((policy) => policy.name))];
  const questionVersionOptions = comparablePolicies.filter(
    (policy) => policy.name === questionPolicyName,
  );
  const shortAnswer = answer ? conciseAnswer(answer) : "";
  const displayedEvidence = orderedEvidence(evidence, answeredQuestion, answer);
  const primarySource = displayedEvidence[0];
  const hasLongerAnswer = shortAnswer !== answer.trim().replace(/\s+/g, " ");

  async function handleQuestion(event) {
    event.preventDefault();
    setAsking(true);
    setAnswer("");
    setEvidence([]);
    setEvidenceOpen(false);
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
      setAnsweredQuestion(question);
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
                setEvidenceOpen(false);
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
                setEvidenceOpen(false);
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
          <p className="concise-answer">{shortAnswer}</p>
          {primarySource && (
            <>
              <p className="primary-source">{sourceLabel(primarySource)}</p>
              <button
                type="button"
                className="evidence-toggle"
                aria-expanded={evidenceOpen}
                aria-controls="ask-evidence-details"
                onClick={() => setEvidenceOpen((open) => !open)}
              >
                {evidenceOpen ? "Hide evidence" : "View evidence"}
                <span aria-hidden="true">{evidenceOpen ? "−" : "+"}</span>
              </button>

              {evidenceOpen && (
                <div
                  id="ask-evidence-details"
                  className="evidence-details"
                  role="region"
                  aria-label="Evidence details"
                >
                  {hasLongerAnswer && (
                    <div className="full-answer">
                      <span>Full answer</span>
                      <p>{answer}</p>
                    </div>
                  )}
                  <div className="sources">
                    <span>Supporting evidence</span>
                    <div className="evidence-list">
                      {displayedEvidence.map((item, index) => (
                        <article
                          className={`evidence-item${index === 0 ? " primary-evidence" : ""}`}
                          key={`${item.version}-${item.page_number}-${index}`}
                        >
                          {index === 0 && <strong>Primary source</strong>}
                          <div className="evidence-metadata">
                            <small className="evidence-meta">Policy: {item.policy_name}</small>
                            <small className="evidence-meta">Version: {item.version}</small>
                            <small className="evidence-meta">Page: {item.page_number}</small>
                          </div>
                          <small className="evidence-meta">Relevant source text</small>
                          <blockquote className="evidence-text">{item.text}</blockquote>
                        </article>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}


export default AskPage;
