import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ImpactPage from "./ImpactPage.jsx";

const policies = [
  { id: 1, family_id: 7, name: "Attendance", version: "2025", status: "SUPERSEDED", attendance_requirement: 75 },
  { id: 2, family_id: 7, name: "Attendance", version: "2026", status: "CURRENT", attendance_requirement: 85 },
  { id: 3, family_id: 9, name: "Other", version: "2027", status: "VERIFIED", attendance_requirement: 90 },
];
const evidence = (version, value, clause) => ({
  policy_name: "Attendance", version, page_number: clause, clause_id: clause,
  source_text: `The minimum attendance requirement is ${value}% in each course.`,
});

beforeEach(() => {
  global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({
    run_id: 1, attendance: 80, impact: "NEWLY_NON_COMPLIANT",
    old_policy: { version: "2025", attendance_requirement: 75, result: "PASS", evidence: evidence("2025", 75, 4) },
    new_policy: { version: "2026", attendance_requirement: 85, result: "FAIL", evidence: evidence("2026", 85, 11) },
  }) });
});
afterEach(() => cleanup());

it("uses only newer same-family versions and reveals durable source evidence", async () => {
  const user = userEvent.setup();
  render(<ImpactPage policies={policies} />);
  const selects = screen.getAllByRole("combobox");
  await user.selectOptions(selects[0], "1");
  expect([...selects[1].options].map((option) => option.textContent)).toEqual([
    "Select a newer version…", "2026 (CURRENT) — 85%",
  ]);
  await user.selectOptions(selects[1], "2");
  await user.type(screen.getByRole("spinbutton"), "80");
  await user.click(screen.getByRole("button", { name: "Calculate impact" }));
  expect(await screen.findByText("NEWLY NON COMPLIANT")).toBeTruthy();
  expect(screen.queryByText(/minimum attendance requirement is 75%/)).toBeNull();
  await user.click(screen.getByText("View old and new source evidence"));
  expect(screen.getByText(/minimum attendance requirement is 75%/)).toBeTruthy();
  expect(screen.getByText(/minimum attendance requirement is 85%/)).toBeTruthy();
  expect(screen.getByText("Page 11 · Clause 11")).toBeTruthy();
});
