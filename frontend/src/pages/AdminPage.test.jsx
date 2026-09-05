import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AdminPage from "./AdminPage.jsx";

const DRAFT_POLICY = {
  id: 1,
  name: "Academic Attendance Policy",
  version: "2026",
  attendance_requirement: 80,
  status: "DRAFT",
};

const VERIFIED_POLICY = {
  id: 2,
  name: "Library Policy",
  version: "2026",
  attendance_requirement: 60,
  status: "VERIFIED",
};

function renderAdminPage({ policies = [DRAFT_POLICY], adminToken = "token" } = {}) {
  const onLoadPolicies = vi.fn();
  const onLoginStateChange = vi.fn();
  render(
    <AdminPage
      policies={policies}
      adminToken={adminToken}
      onLoginStateChange={onLoginStateChange}
      onLoadPolicies={onLoadPolicies}
    />,
  );
  return { onLoadPolicies, onLoginStateChange };
}

beforeEach(() => {
  vi.restoreAllMocks();
  global.fetch = vi.fn();
});

afterEach(() => {
  cleanup();
});

describe("AdminPage delete button", () => {
  it("shows a Delete button for DRAFT policies when logged in", () => {
    renderAdminPage();

    expect(screen.getByRole("button", { name: "Delete" })).toBeTruthy();
  });

  it("does not show a Delete button for non-DRAFT policies", () => {
    // Non-DRAFT policies never reach the review list; only drafts render.
    renderAdminPage({ policies: [VERIFIED_POLICY] });

    expect(screen.getByText("No draft policies awaiting review.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("asks for browser confirmation before deleting", async () => {
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...DRAFT_POLICY, deleted: true }),
    });

    renderAdminPage();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(confirmSpy).toHaveBeenCalledTimes(1);
    expect(confirmSpy.mock.calls[0][0]).toContain("Academic Attendance Policy");
    expect(confirmSpy.mock.calls[0][0]).toContain("2026");
  });

  it("does nothing when confirmation is cancelled", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(false);

    renderAdminPage();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    expect(global.fetch).not.toHaveBeenCalled();
  });

  it("sends DELETE with the admin token and refreshes the list", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...DRAFT_POLICY, deleted: true }),
    });
    const { onLoadPolicies } = renderAdminPage();

    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
    const [path, options] = global.fetch.mock.calls[0];
    expect(path).toContain("/policies/1");
    expect(options.method).toBe("DELETE");
    expect(options.headers.Authorization).toBe("Bearer token");
    await waitFor(() => {
      expect(onLoadPolicies).toHaveBeenCalled();
    });
    expect(
      screen.getByText("Academic Attendance Policy 2026 deleted."),
    ).toBeTruthy();
  });

  it("shows an error message when deletion fails", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    global.fetch.mockResolvedValue({
      ok: false,
      json: () => Promise.resolve({ detail: "Only DRAFT policies can be deleted." }),
    });

    renderAdminPage();
    await user.click(screen.getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      expect(
        screen.getByText("Only DRAFT policies can be deleted."),
      ).toBeTruthy();
    });
  });
});

describe("AdminPage login gate", () => {
  it("shows the login form instead of review controls when logged out", () => {
    renderAdminPage({ adminToken: "" });

    expect(screen.getByText("Admin email")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});