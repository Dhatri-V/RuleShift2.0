import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import ComparePage from "./ComparePage.jsx";


const policies = [
  { id: 4, family_id: 10, name: "Attendance Policy", version: "2024", status: "VERIFIED", attendance_requirement: 70 },
  { id: 5, family_id: 10, name: "Attendance Policy", version: "2025", status: "VERIFIED", attendance_requirement: 75 },
  { id: 6, family_id: 10, name: "Attendance Policy", version: "2026", status: "VERIFIED", attendance_requirement: 80 },
  { id: 7, family_id: 10, name: "Attendance Policy", version: "2027", status: "VERIFIED", attendance_requirement: 85 },
  { id: 10, family_id: 10, name: "Attendance Policy", version: "2028", status: "DRAFT", attendance_requirement: 90 },
  { id: 8, family_id: 20, name: "Other Policy", version: "2028", status: "VERIFIED", attendance_requirement: 90 },
  { id: 9, family_id: 20, name: "Attendance Policy", version: "2029", status: "VERIFIED", attendance_requirement: 95 },
];


function optionLabels(select) {
  return Array.from(select.options).map((option) => option.textContent);
}


afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


it.each([
  ["4", [
    "Select a newer version…",
    "2025 (VERIFIED) — 75%",
    "2026 (VERIFIED) — 80%",
    "2027 (VERIFIED) — 85%",
  ]],
  ["5", [
    "Select a newer version…",
    "2026 (VERIFIED) — 80%",
    "2027 (VERIFIED) — 85%",
  ]],
  ["6", [
    "Select a newer version…",
    "2027 (VERIFIED) — 85%",
  ]],
])("old version %s offers only its newer verified same-family versions", async (oldId, expectedOptions) => {
  const user = userEvent.setup();
  render(<ComparePage policies={policies} />);
  const oldSelect = screen.getByLabelText("Old policy version");
  const newSelect = screen.getByLabelText("New policy version");

  await user.selectOptions(oldSelect, oldId);
  expect(optionLabels(newSelect)).toEqual(expectedOptions);
});


it("disables the new-version selector with a clear latest-version state", async () => {
  const user = userEvent.setup();
  render(<ComparePage policies={policies} />);
  await user.selectOptions(screen.getByLabelText("Old policy version"), "7");

  const newSelect = screen.getByLabelText("New policy version");
  expect(newSelect.disabled).toBe(true);
  expect(optionLabels(newSelect)).toEqual(["No newer verified version available"]);
  expect(screen.getByText("This is the latest version in the selected policy family.")).toBeTruthy();
});


it("clears a selected new version immediately when the old version changes", async () => {
  const user = userEvent.setup();
  render(<ComparePage policies={policies} />);
  const oldSelect = screen.getByLabelText("Old policy version");
  const newSelect = screen.getByLabelText("New policy version");

  await user.selectOptions(oldSelect, "4");
  await user.selectOptions(newSelect, "5");
  expect(newSelect.value).toBe("5");

  await user.selectOptions(oldSelect, "6");
  expect(newSelect.value).toBe("");
  expect(optionLabels(newSelect)).toEqual([
    "Select a newer version…",
    "2027 (VERIFIED) — 85%",
  ]);
  expect(screen.getByRole("button", { name: "Compare versions" }).disabled).toBe(true);
});


it("submits the selected old and new version IDs and renders the comparison", async () => {
  global.fetch = vi.fn(async () => ({
    ok: true,
    json: async () => ({
      old_policy: policies.find((policy) => policy.id === 5),
      new_policy: policies.find((policy) => policy.id === 7),
      direction: "INCREASED",
      difference: 10,
    }),
  }));
  const user = userEvent.setup();
  render(<ComparePage policies={policies} />);
  await user.selectOptions(screen.getByLabelText("Old policy version"), "5");
  await user.selectOptions(screen.getByLabelText("New policy version"), "7");

  const button = screen.getByRole("button", { name: "Compare versions" });
  expect(button.disabled).toBe(false);
  await user.click(button);
  await screen.findByText("Requirement increased");

  const [, options] = global.fetch.mock.calls[0];
  expect(JSON.parse(options.body)).toEqual({ old_policy_id: 5, new_policy_id: 7 });
});
