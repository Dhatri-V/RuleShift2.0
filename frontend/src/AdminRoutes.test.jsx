import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import App from "./App.jsx";
import { ADMIN_TOKEN_KEY } from "./api.js";

const draft = { id: 1, name: "Attendance", version: "v1", status: "DRAFT", attendance_requirement: 75 };
const verified = { id: 2, name: "Attendance", version: "v2", status: "VERIFIED", attendance_requirement: 85 };

function LocationProbe() {
  const location = useLocation();
  const navigate = useNavigate();
  return <><output aria-label="Current route">{location.pathname}</output>
    <button onClick={() => navigate(-1)}>Browser back</button></>;
}

function mount(path = "/", token = "", handler = () => undefined) {
  if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token);
  global.fetch = vi.fn(async (url, options) => {
    const response = handler(url, options);
    if (response) return response;
    if (url.endsWith("/health")) return json({ status: "ok" });
    if (url.endsWith("/policies") && !options?.method) return json([draft, verified]);
    if (url.endsWith("/auth/login")) return json({ access_token: "existing-api-token" });
    throw new Error(`Unexpected request ${url}`);
  });
  render(<MemoryRouter initialEntries={["/", path]}><App /><LocationProbe /></MemoryRouter>);
}

function json(data, status = 200) { return { ok: status < 400, status, json: async () => data }; }
beforeEach(() => { localStorage.clear(); });
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks(); });

it.each(["/", "/ask", "/impact", "/compare", "/policies"])("keeps %s student-facing without admin forms", async (path) => {
  mount(path);
  await screen.findByText("API connected");
  expect(screen.queryByLabelText("Admin password")).toBeNull();
  expect(screen.queryByRole("heading", { name: "Upload a policy" })).toBeNull();
  expect(screen.getByRole("link", { name: "Admin", exact: true }).getAttribute("href")).toBe("/admin/login");
});

it.each(["/admin", "/admin/dashboard", "/admin/unknown"])("redirects anonymous visits from %s to login", async (path) => {
  mount(path);
  await screen.findByRole("heading", { name: "Admin login" });
  expect(screen.getByLabelText("Current route").textContent).toBe("/admin/login");
  expect(screen.queryByRole("button", { name: "Upload policy" })).toBeNull();
});

it("uses the existing login API and token key, then redirects to the dashboard", async () => {
  const user = userEvent.setup();
  mount("/admin/login");
  await user.type(screen.getByLabelText("Admin email"), "admin@example.edu");
  await user.type(screen.getByLabelText("Admin password"), "change-me");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByRole("heading", { name: "Admin dashboard" });
  expect(screen.getByLabelText("Current route").textContent).toBe("/admin/dashboard");
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBe("existing-api-token");
  const call = global.fetch.mock.calls.find(([url]) => url.endsWith("/auth/login"));
  expect(call[1].method).toBe("POST");
  expect(JSON.parse(call[1].body)).toEqual({ email: "admin@example.edu", password: "change-me" });
  expect(screen.queryByLabelText("Admin password")).toBeNull();
  for (const name of ["Upload Policy", "Review / Verify Policy", "Manage Policy Versions", "Compare Policies"])
    expect(screen.getByRole("link", { name, exact: true })).toBeTruthy();
});

it("keeps failed login on the login page without creating a session", async () => {
  const user = userEvent.setup();
  mount("/admin/login", "", (url) => url.endsWith("/auth/login") ? json({ detail: "Invalid admin email or password." }, 401) : undefined);
  await user.type(screen.getByLabelText("Admin email"), "admin@example.edu");
  await user.type(screen.getByLabelText("Admin password"), "wrong");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await screen.findByText("Invalid admin email or password.");
  expect(screen.getByLabelText("Current route").textContent).toBe("/admin/login");
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull();
});

it.each(["/admin", "/admin/login", "/admin/dashboard"])("restores the stored session at %s", async (path) => {
  mount(path, "stored-token");
  await screen.findByRole("heading", { name: "Admin dashboard" });
  expect(screen.getByLabelText("Current route").textContent).toBe("/admin/dashboard");
  expect(screen.getByRole("link", { name: "Admin", exact: true }).getAttribute("href")).toBe("/admin/dashboard");
});

it("logs out, clears storage and keeps admin controls out of browser-back history", async () => {
  const user = userEvent.setup();
  mount("/admin/dashboard", "stored-token");
  await user.click(screen.getByRole("button", { name: "Log out" }));
  await screen.findByRole("heading", { name: "Admin login" });
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull();
  await user.click(screen.getByRole("button", { name: "Browser back" }));
  expect(screen.queryByRole("heading", { name: "Admin dashboard" })).toBeNull();
  await user.click(screen.getByRole("link", { name: "Admin", exact: true }));
  await screen.findByRole("heading", { name: "Admin login" });
});

it("returns to login when the backend rejects an admin token", async () => {
  const user = userEvent.setup();
  mount("/admin/dashboard", "expired-token", (url) => url.endsWith("/mark-current") ? json({ detail: "Admin session has expired." }, 401) : undefined);
  await user.click(await screen.findByRole("button", { name: "Mark current" }));
  await screen.findByRole("heading", { name: "Admin login" });
  expect(localStorage.getItem(ADMIN_TOKEN_KEY)).toBeNull();
});

it("manages versions through the existing authenticated mark-current endpoint", async () => {
  const user = userEvent.setup();
  mount("/admin/dashboard", "stored-token", (url) => url.endsWith("/mark-current") ? json({ ...verified, status: "CURRENT" }) : undefined);
  await user.click(await screen.findByRole("button", { name: "Mark current" }));
  await screen.findByText("Attendance v2 marked current.");
  const call = global.fetch.mock.calls.find(([url]) => url.endsWith("/policies/2/mark-current"));
  expect(call[1]).toEqual({ method: "POST", headers: { Authorization: "Bearer stored-token" } });
  await waitFor(() => expect(global.fetch.mock.calls.filter(([url]) => url.endsWith("/policies")).length).toBe(2));
});

it("preserves authenticated PDF upload within the dashboard", async () => {
  const user = userEvent.setup();
  mount("/admin/dashboard", "stored-token", (url) => url.endsWith("/policies/upload") ? json(draft) : undefined);
  await user.type(screen.getByRole("textbox", { name: "Policy name", exact: true }), "Attendance");
  await user.type(screen.getByRole("textbox", { name: "Version", exact: true }), "v1");
  await user.upload(screen.getByLabelText(/Policy PDF/), new File(["%PDF-demo"], "policy.pdf", { type: "application/pdf" }));
  expect(screen.getByText("policy.pdf")).toBeTruthy();
  // jsdom still reports valueMissing for user-event's synthetic FileList.
  // Exercise submission and its actual FormData without changing browser validation.
  fireEvent.submit(screen.getByRole("button", { name: "Upload policy" }).closest("form"));
  await screen.findByText(/Attendance v1 uploaded/);
  const call = global.fetch.mock.calls.find(([url]) => url.endsWith("/policies/upload"));
  expect(call[1].headers.Authorization).toBe("Bearer stored-token");
  expect(call[1].body.get("policy_name")).toBe("Attendance");
  expect(call[1].body.get("file").name).toBe("policy.pdf");
});


it.each([
  ["75", "Verify", "/verify", "POST", "Attendance v1 verified."],
  ["80", "Save correction", "/rule", "PATCH", "Attendance v1 updated to 80% attendance."],
])("preserves admin rule review at %s percent", async (value, button, endpoint, method, message) => {
  const user = userEvent.setup();
  mount("/admin/dashboard", "stored-token", (url) => url.endsWith(endpoint) ? json({ ...draft, attendance_requirement: Number(value) }) : undefined);
  const input = await screen.findByRole("spinbutton", { name: "Attendance requirement %" });
  await user.type(input, value);
  await user.click(screen.getByRole("button", { name: button, exact: true }));
  await screen.findByText(message);
  const call = global.fetch.mock.calls.find(([url]) => url.endsWith(`/policies/1${endpoint}`));
  expect(call[1].method).toBe(method);
  expect(call[1].headers.Authorization).toBe("Bearer stored-token");
});
