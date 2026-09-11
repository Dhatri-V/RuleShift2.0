import { useState } from "react";

import { Navigate } from "react-router-dom";
import ComparePage from "./ComparePage.jsx";
import Message from "../components/Message.jsx";
import {
  adminHeaders,
  apiRequest,
} from "../api.js";


function AdminPage({ policies, adminToken, onLogout, onLoadPolicies, policyListError = "" }) {
  const [policyName, setPolicyName] = useState("");
  const [policyVersion, setPolicyVersion] = useState("");
  const [policyFile, setPolicyFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState({ type: "", text: "" });

  const [draftRuleValues, setDraftRuleValues] = useState({});
  const [reviewingPolicyId, setReviewingPolicyId] = useState(null);
  const [reviewMessage, setReviewMessage] = useState({ type: "", text: "" });

  const draftPolicies = policies.filter((policy) => policy.status === "DRAFT" || policy.source_check?.status === "MISMATCH");

  async function adminRequest(path, options) {
    try {
      return await apiRequest(path, options);
    } catch (error) {
      if (error.status === 401) onLogout();
      throw error;
    }
  }

  async function handleMarkCurrent(policy) {
    setReviewingPolicyId(policy.id);
    setReviewMessage({ type: "", text: "" });
    try {
      const data = await adminRequest(`/policies/${policy.id}/mark-current`, {
        method: "POST", headers: adminHeaders(adminToken),
      });
      setReviewMessage({ type: "success", text: `${data.name} ${data.version} marked current.` });
      await onLoadPolicies();
    } catch (error) {
      setReviewMessage({ type: "error", text: error.message });
    } finally {
      setReviewingPolicyId(null);
    }
  }

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
      const data = await adminRequest("/policies/upload", {
        method: "POST",
        body: formData,
        headers: adminHeaders(adminToken),
      });

      setUploadMessage({
        type: "success",
        text: `${data.name} ${data.version} uploaded. Attendance requirement: ${data.attendance_requirement}%.`,
      });
      setPolicyFile(null);
      setFileInputKey((currentKey) => currentKey + 1);
      await onLoadPolicies();
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
      const data = await adminRequest(`/policies/${policy.id}/rule`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...adminHeaders(adminToken),
        },
        body: JSON.stringify({
          attendance_requirement: Number(draftRuleValues[policy.id]),
        }),
      });
      setReviewMessage({
        type: "success",
        text: `${data.name} ${data.version} updated to ${data.attendance_requirement}% attendance.`,
      });
      await onLoadPolicies();
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
      const data = await adminRequest(`/policies/${policy.id}/verify`, {
        method: "POST",
        headers: adminHeaders(adminToken),
      });
      setReviewMessage({
        type: "success",
        text: `${data.name} ${data.version} verified.`,
      });
      await onLoadPolicies();
    } catch (error) {
      setReviewMessage({ type: "error", text: error.message });
    } finally {
      setReviewingPolicyId(null);
    }
  }

  async function handleDelete(policy) {
    const confirmed = window.confirm(
      `Delete draft policy "${policy.name}" version ${policy.version}? ` +
        "This removes the draft and its indexed text and cannot be undone.",
    );
    if (!confirmed) {
      return;
    }

    setReviewingPolicyId(policy.id);
    setReviewMessage({ type: "", text: "" });

    try {
      const data = await adminRequest(`/policies/${policy.id}`, {
        method: "DELETE",
        headers: adminHeaders(adminToken),
      });
      setReviewMessage({
        type: "success",
        text: `${data.name} ${data.version} deleted.`,
      });
      await onLoadPolicies();
    } catch (error) {
      setReviewMessage({ type: "error", text: error.message });
    } finally {
      setReviewingPolicyId(null);
    }
  }

  if (!adminToken) return <Navigate to="/admin/login" replace />;

  return (
    <div className="admin-dashboard">
      <header className="admin-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h2>Admin dashboard</h2>
          <p>Upload policies, review extracted rules, and manage versions.</p>
        </div>
        <button className="text-button" type="button" onClick={onLogout}>Log out</button>
      </header>
      <nav className="admin-sections" aria-label="Admin sections">
        <a className="nav-link" href="#admin-upload">Upload Policy</a>
        <a className="nav-link" href="#admin-review">Review / Verify Policy</a>
        <a className="nav-link" href="#admin-versions">Manage Policy Versions</a>
        <a className="nav-link" href="#admin-compare">Compare Policies</a>
      </nav>
      {policyListError && <div className="message message-error" role="alert">{policyListError}</div>}
      <Message message={reviewMessage} />
      <section id="admin-upload" className="panel upload-panel" aria-labelledby="upload-heading">
        <div className="panel-heading">
          <span className="step">01</span>
          <div>
            <h3 id="upload-heading">Upload a policy</h3>
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

          <button type="submit" disabled={uploading || !adminToken}>
            {uploading ? "Uploading and analyzing…" : "Upload policy"}
          </button>
          <Message message={uploadMessage} />
        </form>
      </section>

      <section id="admin-review" className="panel admin-panel" aria-labelledby="review-heading">
        <div className="panel-heading">
          <span className="step">AR</span>
          <div>
            <h3 id="review-heading">Review / Verify Policy</h3>
            <p>Check the source evidence and save corrections before verification. Repairing a reviewed mismatch returns it to DRAFT.</p>
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
                    <span>Version {policy.version}</span>
                    <span className={`admin-status status-${policy.status.toLowerCase()}`}>{policy.status}</span>
                    <span>Stored attendance: {policy.attendance_requirement}%</span>
                    {policy.source_check && <p className={policy.source_check.status === "MISMATCH" ? "message message-error" : "source-note"}>{policy.source_check.message}</p>}
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
                      disabled={reviewBusy || invalidRule || hasUnsavedRule || policy.source_check?.status === "MISMATCH"}
                      onClick={() => handleVerify(policy)}
                      title={hasUnsavedRule ? "Save the correction before verifying." : ""}
                    >
                      {reviewingPolicyId === policy.id && !hasUnsavedRule
                        ? "Verifying…"
                        : "Verify"}
                    </button>
                    {policy.status === "DRAFT" && <button
                      className="danger-button"
                      type="button"
                      disabled={reviewBusy}
                      onClick={() => handleDelete(policy)}
                      title="Delete this draft policy and its indexed text."
                    >
                      {reviewingPolicyId === policy.id ? "Deleting…" : "Delete"}
                    </button>}
                  </div>
                </form>
              );
            })}
          </div>
        )}
      </section>
      <section id="admin-versions" className="panel" aria-labelledby="versions-heading">
        <div className="panel-heading">
          <div>
            <h3 id="versions-heading">Manage Policy Versions</h3>
            <p>Review version status and choose the current verified version.</p>
          </div>
          <button className="text-button" type="button" onClick={onLoadPolicies}>Refresh versions</button>
        </div>
        {policies.length === 0 ? <div className="empty-state">No policies saved yet.</div> : (
          <div className="version-management-list">
            {policies.map((policy) => (
              <article className="policy-item" key={policy.id}>
                <div>
                  <strong>{policy.name}</strong>
                  <span>Version {policy.version} · {policy.attendance_requirement}% attendance</span>
                </div>
                <div><span className={`admin-status status-${policy.status.toLowerCase()}`}>{policy.status}</span>
                {policy.source_check && <p className={policy.source_check.status === "MISMATCH" ? "message message-error" : "source-note"}>{policy.source_check.message}</p>}</div>
                <div className="review-actions">
                  {(policy.status === "DRAFT" || policy.source_check?.status === "MISMATCH") && <a className="nav-link" href="#admin-review">Review draft</a>}
                  {policy.status === "VERIFIED" && (!policy.source_check || ["MATCH", "UNAVAILABLE"].includes(policy.source_check.status)) && (
                    <button type="button" disabled={reviewingPolicyId !== null} onClick={() => handleMarkCurrent(policy)}>
                      Mark current
                    </button>
                  )}
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
      <div id="admin-compare"><ComparePage policies={policies} /></div>
    </div>
  );
}


export default AdminPage;