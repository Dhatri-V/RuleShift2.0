import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "./App.jsx";

function mount({ health = { status: "ok" }, policiesError = false, healthError = false } = {}) {
  global.fetch = vi.fn(async (url) => {
    if (url.endsWith("/health")) {
      if (healthError) throw new Error("Network unavailable");
      return { ok: true, json: async () => health };
    }
    if (url.endsWith("/policies")) {
      if (policiesError) throw new Error("Policy database unavailable");
      return { ok: true, json: async () => [] };
    }
    throw new Error(`Unexpected endpoint: ${url}`);
  });
  render(<MemoryRouter initialEntries={["/policies"]}><App /></MemoryRouter>);
}

afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("uses /health and stays connected when listing fails", async () => {
  mount({ policiesError: true });
  await screen.findByText("API connected");
  await screen.findByText("Policy database unavailable");
  expect(global.fetch.mock.calls.some(([url]) => url.endsWith("/health"))).toBe(true);
});

it("does not let a successful policy list override a failed health check", async () => {
  mount({ healthError: true });
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  expect(screen.getByText("API offline")).toBeTruthy();
});

it("requires the expected health response", async () => {
  mount({ health: { status: "degraded" } });
  await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(2));
  expect(screen.getByText("API offline")).toBeTruthy();
});

it("rechecks when the window regains focus", async () => {
  mount();
  await screen.findByText("API connected");
  const before = global.fetch.mock.calls.length;
  window.dispatchEvent(new Event("focus"));
  await waitFor(() => expect(global.fetch.mock.calls.length).toBe(before + 1));
});
