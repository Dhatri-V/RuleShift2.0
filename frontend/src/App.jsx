import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";

import { apiRequest, getStoredAdminToken } from "./api.js";
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
  { path: "/admin", label: "Admin" },
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

  function handleLoginStateChange(token) {
    setAdminToken(token);
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
            path="/admin"
            element={
              <AdminPage
                policies={policies}
                adminToken={adminToken}
                onLoginStateChange={handleLoginStateChange}
                onLoadPolicies={loadPolicies}
              />
            }
          />
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