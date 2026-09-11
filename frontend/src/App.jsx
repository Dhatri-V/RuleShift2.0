import { useEffect, useState } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";

import { apiRequest, clearAdminToken, getStoredAdminToken } from "./api.js";
import AdminLoginPage from "./pages/AdminLoginPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";
import AskPage from "./pages/AskPage.jsx";
import ComparePage from "./pages/ComparePage.jsx";
import HomePage from "./pages/HomePage.jsx";
import ImpactPage from "./pages/ImpactPage.jsx";
import PoliciesPage from "./pages/PoliciesPage.jsx";


const NAV_ITEMS = [
  { path: "/", label: "RuleShift", end: true },
  { path: "/policies", label: "Policies" },
  { path: "/compare", label: "Compare" },
  { path: "/impact", label: "Student Impact" },
  { path: "/ask", label: "Ask" },
];


function App() {
  const [apiOnline, setApiOnline] = useState(false);
  const [policies, setPolicies] = useState([]);
  const [policyListError, setPolicyListError] = useState("");
  const [adminToken, setAdminToken] = useState(() => getStoredAdminToken());

  async function loadPolicies() {
    try {
      const data = await apiRequest("/policies");
      setPolicies(data);
      setPolicyListError("");
    } catch (error) {
      setPolicyListError(error.message);
    }
  }

  useEffect(() => {
    let active = true;
    const controller = new AbortController();

    async function checkApi() {
      try {
        const data = await apiRequest("/health", { signal: controller.signal });
        if (active) setApiOnline(data.status === "ok");
      } catch {
        if (active) setApiOnline(false);
      }
    }

    checkApi();
    loadPolicies();
    const interval = window.setInterval(checkApi, 15000);
    window.addEventListener("focus", checkApi);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(interval);
      window.removeEventListener("focus", checkApi);
    };
  }, []);

  function handleLoginStateChange(token) {
    setAdminToken(token);
  }

  function handleLogout() {
    clearAdminToken();
    setAdminToken("");
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

      <nav className="main-nav" aria-label="Main navigation">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.end}
            className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
          >
            {item.label}
          </NavLink>
        ))}
        <NavLink
          to={adminToken ? "/admin/dashboard" : "/admin/login"}
          className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}
        >
          Admin
        </NavLink>
      </nav>

      <main>
        <Routes>
          <Route path="/" element={<HomePage policies={policies} />} />
          <Route
            path="/policies"
            element={
              <PoliciesPage
                policies={policies}
                policyListError={policyListError}
                onRefresh={loadPolicies}
              />
            }
          />
          <Route path="/compare" element={<ComparePage policies={policies} />} />
          <Route path="/impact" element={<ImpactPage policies={policies} />} />
          <Route path="/ask" element={<AskPage policies={policies} />} />
          <Route
            path="/admin/login"
            element={adminToken
              ? <Navigate to="/admin/dashboard" replace />
              : <AdminLoginPage onLoginStateChange={handleLoginStateChange} />}
          />
          <Route
            path="/admin/dashboard"
            element={adminToken ? (
              <AdminPage
                policies={policies}
                policyListError={policyListError}
                adminToken={adminToken}
                onLogout={handleLogout}
                onLoadPolicies={loadPolicies}
              />
            ) : <Navigate to="/admin/login" replace />}
          />
          <Route path="/admin/*" element={
            <Navigate to={adminToken ? "/admin/dashboard" : "/admin/login"} replace />
          } />
        </Routes>
      </main>

      <footer>
        <span>RuleShift 2.0</span>
        <span>Deterministic policy impact analysis</span>
      </footer>
    </div>
  );
}


export default App;