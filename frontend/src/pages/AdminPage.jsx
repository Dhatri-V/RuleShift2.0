import { useState } from "react";

import Message from "../components/Message.jsx";
import {
  adminHeaders,
  apiRequest,
  clearAdminToken,
  storeAdminToken,
} from "../api.js";


function AdminPage({ policies, adminToken, onLoginStateChange, onLoadPolicies }) {
  const [policyName, setPolicyName] = useState("");
  const [policyVersion, setPolicyVersion] = useState("");
  const [policyFile, setPolicyFile] = useState(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState({ type: "", text: "" });

  const [draftRuleValues, setDraftRuleValues] = useState({});
  const [reviewingPolicyId, setReviewingPolicyId] = useState(null);
  const [reviewMessage, setReviewMessage] = useState({ type: "", text: "" });

  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminLoggingIn, setAdminLoggingIn] = useState(false);
  const [adminMessage, setAdminMessage] = useState({ type: "", text: "" });

  const draftPolicies = policies.filter((policy) => policy.status === "DRAFT");

  async function handleAdminLogin(event) {
    event.preventDefault();
    setAdminLoggingIn(true);
    setAdminMessage({ type: "", text: "" });

    try {
      const data = await apiRequest("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: adminEmail, password: adminPassword }),
      });

      storeAdminToken(data.access_token);
      onLoginStateChange(data.access_token);
      setAdminPassword("");
      setAdminMessage({ type: "success", text: "Logged in as admin." });
    } catch (error) {
      setAdminMessage({ type: "error", text: error.message });
    } finally {
      setAdminLoggingIn(false);
    }
  }

  function handleAdminLogout() {
    clearAdminToken();
    onLoginStateChange("");
    setAdminEmail("");
    setAdminPassword("");
    setAdminMessage({ type: "", text: "" });
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
      const data = await apiRequest("/policies/upload", {
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
      const data = await apiRequest(`/policies/${policy.id}/rule`, {
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
      const data = await apiRequest(`/policies/${policy.id}/verify`, {
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

  return (
    <>
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

          <button type="submit" disabled={uploading || !adminToken}>
            {uploading ? "Uploading and analyzing…" : "Upload policy"}
          </button>
          {!adminToken && (
            <small className="admin-hint">Admin login required to upload policies.</small>
          )}
          <Message message={uploadMessage} />
        </form>
      </section>

      <section className="panel admin-panel">
        <div className="panel-heading">
          <span className="step">AR</span>
          <div>
            <h3>Admin review</h3>
            <p>Correct extracted attendance rules before verification.</p>
          </div>
          {adminToken ? (
            <button className="text-button" type="button" onClick={handleAdminLogout}>
              Log out
            </button>
          ) : null}
        </div>

        {!adminToken ? (
          <form className="admin-login" onSubmit={handleAdminLogin}>
            <div className="form-row">
              <label>
                Admin email
                <input
                  type="email"
                  value={adminEmail}
                  onChange={(event) => setAdminEmail(event.target.value)}
                  placeholder="admin@example.edu"
                  autoComplete="username"
                  required
                />
              </label>
              <label>
                Admin password
                <input
                  type="password"
                  value={adminPassword}
                  onChange={(event) => setAdminPassword(event.target.value)}
                  placeholder="••••••••"
                  autoComplete="current-password"
                  required
                />
              </label>
            </div>
            <button type="submit" disabled={adminLoggingIn}>
              {adminLoggingIn ? "Signing in…" : "Admin login"}
            </button>
            <Message message={adminMessage} />
          </form>
        ) : draftPolicies.length === 0 ? (
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
        {adminToken ? <Message message={reviewMessage} /> : null}
      </section>
    </>
  );
}


export default AdminPage;