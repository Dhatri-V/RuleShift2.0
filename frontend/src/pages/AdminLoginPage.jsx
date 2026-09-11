import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { apiRequest, storeAdminToken } from "../api.js";
import Message from "../components/Message.jsx";

export default function AdminLoginPage({ onLoginStateChange }) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState({ type: "", text: "" });

  async function handleLogin(event) {
    event.preventDefault();
    setBusy(true);
    setMessage({ type: "", text: "" });
    try {
      const data = await apiRequest("/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      storeAdminToken(data.access_token);
      onLoginStateChange(data.access_token);
      setPassword("");
      navigate("/admin/dashboard", { replace: true });
    } catch (error) {
      setMessage({ type: "error", text: error.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel admin-login-page">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h2>Admin login</h2>
          <p>Sign in to upload policies, review rules, and manage versions.</p>
        </div>
      </div>
      <form onSubmit={handleLogin}>
        <label>Admin email
          <input type="email" autoComplete="username" required value={email}
            onChange={(event) => setEmail(event.target.value)} placeholder="admin@example.edu" />
        </label>
        <label>Admin password
          <input type="password" autoComplete="current-password" required value={password}
            onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <Message message={message} />
      </form>
      <Link className="student-return" to="/">Back to student workspace</Link>
    </section>
  );
}
