import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { MemoryRouter, Route, Routes } from "react-router-dom";
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
  const onLogout = vi.fn();
  render(
    <MemoryRouter initialEntries={["/admin/dashboard"]}><Routes>
      <Route path="/admin/login" element={<div>Admin sign-in route</div>} />
      <Route path="/admin/dashboard" element={<AdminPage
      policies={policies}
      adminToken={adminToken}
      onLogout={onLogout}
      onLoadPolicies={onLoadPolicies}
    />} />
    </Routes></MemoryRouter>,
  );
  return { onLoadPolicies, onLogout };
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
  it("redirects to the dedicated login route when logged out", () => {
    renderAdminPage({ adminToken: "" });

    expect(screen.getByText("Admin sign-in route")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });
});

describe("Source integrity and admin sections", () => {
  it("shows a reviewed mismatch in review and prevents verification/current", () => {
    renderAdminPage({ policies: [{ ...VERIFIED_POLICY, source_check: { status: "MISMATCH", expected_value: 85, message: "Source requires 85% (page 11); stored value is 60%." } }] });
    expect(screen.getByRole("region", {name: "Upload a policy"})).toBeTruthy();
    expect(screen.getByRole("region", {name: "Review / Verify Policy"})).toBeTruthy();
    expect(screen.getByRole("region", {name: "Manage Policy Versions"})).toBeTruthy();
    expect(screen.getAllByText("Source requires 85% (page 11); stored value is 60%.").length).toBe(2);
    expect(screen.getByRole("button", {name: "Verify"}).disabled).toBe(true);
    expect(screen.queryByRole("button", {name: "Mark current"})).toBeNull();
  });
});


it.each([
  ["ABSENT", "Source attendance ABSENT: no supported explicit ordinary attendance provision was found. Review the PDF before verification."],
  ["AMBIGUOUS", "Source attendance AMBIGUOUS: competing ordinary requirements: 80% (pages 1, 3); 85% (pages 2). Resolve the source conflict before verification."]
])("displays %s source details and blocks current promotion", (status, message) => {
  renderAdminPage({ policies: [{ ...VERIFIED_POLICY, source_check: {status, message} }] });
  expect(screen.getByText(message)).toBeTruthy();
  expect(screen.queryByRole("button", {name: "Mark current"})).toBeNull();
});
