import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AskPage from "./AskPage.jsx";


const policies = [
  { id: 1, name: "Academic Attendance", version: "2027", status: "VERIFIED" },
];

const directEvidence = {
  policy_name: "Academic Attendance",
  version: "2027",
  page_number: 11,
  text: "SECTION 03 / ATTENDANCE\n3.1 Ordinary attendance\nThe minimum attendance requirement is 85% in each course.",
};

const relatedEvidence = {
  policy_name: "Academic Attendance",
  version: "2027",
  page_number: 13,
  text: "3.4 Medical condonation\nA student may submit medical evidence when attendance falls within the condonation range.",
};


function json(data) {
  return { ok: true, json: async () => data };
}


async function askQuestion(response = {}) {
  const answer = response.answer || "No. The minimum attendance requirement is 85%, so 84% does not meet the requirement. Contact your department if your attendance record needs correction.";
  const evidence = response.evidence || [relatedEvidence, directEvidence];
  global.fetch = vi.fn(async () => json({ answer, evidence }));
  const user = userEvent.setup();

  render(<AskPage policies={policies} />);
  await user.selectOptions(screen.getByLabelText("Policy name"), "Academic Attendance");
  await user.selectOptions(screen.getByLabelText("Version"), "2027");
  await user.type(
    screen.getByLabelText("Question"),
    "I have 84% attendance. Do I meet the attendance requirement?",
  );
  await user.click(screen.getByRole("button", { name: "Ask RuleShift" }));
  await screen.findByText("No. The minimum attendance requirement is 85%, so 84% does not meet the requirement.");
  return user;
}


afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});


it("shows a concise answer and strongest source while keeping evidence collapsed", async () => {
  await askQuestion();

  expect(screen.getByText("Source: Section 3.1 — Attendance, 2027 policy, page 11")).toBeTruthy();
  expect(screen.getByRole("button", { name: /View evidence/ }).getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByRole("region", { name: "Evidence details" })).toBeNull();
  expect(screen.queryByText("Contact your department if your attendance record needs correction.")).toBeNull();

  const call = global.fetch.mock.calls.find(([url]) => url.endsWith("/ask"));
  expect(JSON.parse(call[1].body)).toEqual({
    policy_name: "Academic Attendance",
    version: "2027",
    question: "I have 84% attendance. Do I meet the attendance requirement?",
  });
});


it("reveals the full answer and all evidence, with direct evidence first, then collapses", async () => {
  const user = await askQuestion();
  const toggle = screen.getByRole("button", { name: /View evidence/ });

  await user.click(toggle);
  const details = screen.getByRole("region", { name: "Evidence details" });
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(screen.getByText("Full answer")).toBeTruthy();
  expect(details.textContent).toContain("Contact your department if your attendance record needs correction.");
  expect(screen.getAllByRole("article")).toHaveLength(2);
  expect(screen.getAllByRole("article")[0].textContent).toContain("Page: 11");
  expect(screen.getAllByRole("article")[0].textContent).toContain("minimum attendance requirement is 85%");
  expect(details.textContent).toContain("Medical condonation");

  await user.click(screen.getByRole("button", { name: /Hide evidence/ }));
  await waitFor(() => expect(screen.queryByRole("region", { name: "Evidence details" })).toBeNull());
  expect(screen.getByRole("button", { name: /View evidence/ }).getAttribute("aria-expanded")).toBe("false");
});
