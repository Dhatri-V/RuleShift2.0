"""Generate the reproducible, fictional 100-page manual-upload handbook.

Uses the project's existing PyMuPDF dependency. No network or AI generation.
Run: python scripts/generate_large_policy_sample.py
"""
from pathlib import Path
import textwrap

import pymupdf


SECTIONS = [
    ("Attendance", "Academic Office", [
        "Students must maintain at least 85 percent attendance in each registered course to meet the ordinary examination attendance requirement.",
        "Attendance is classes attended divided by classes actually held, multiplied by 100. Cancelled classes are excluded from the denominator.",
        "A student at 80 percent does not meet the ordinary threshold. A student at 90 percent meets it; assessment and registration conditions still apply.",
    ], ["Course registers", "Laboratory sessions", "Late registration", "Approved academic travel", "Weekly reporting", "Early warnings", "Record corrections", "Final certification", "Attendance appeals", "Record retention"]),
    ("Examinations", "Examination Office", [
        "Examination registration requires an active course registration, approved attendance eligibility and satisfaction of internal-assessment requirements.",
        "Students must carry the issued admit card and college identity card. Entry closes thirty minutes after the published start time.",
        "Unauthorised notes and electronic communication devices are prohibited. A suspected breach must be documented and referred for a fair hearing.",
    ], ["Registration", "Admit cards", "Timetables", "Seating arrangements", "Invigilation", "Permitted materials", "Disability accommodations", "Absence reporting", "Results publication", "Revaluation"]),
    ("Internal Assessment", "Course Coordinator", [
        "Continuous internal assessment totals 40 marks: class tests contribute 20, assignments contribute 10 and laboratory or seminar work contributes 10.",
        "Students must earn at least 16 marks out of 40. Attendance eligibility alone does not establish marks eligibility.",
        "An 18-out-of-40 score satisfies the marks minimum; a 12-out-of-40 score does not. Approved marks are recorded without rounding up a failing score.",
    ], ["Assessment plans", "Class tests", "Assignments", "Laboratory records", "Seminar evaluation", "Rubrics", "Missed assessments", "Moderation", "Marks review", "Final submission"]),
    ("Condonation", "Dean Academic", [
        "Medical condonation may be considered when course attendance is at least 80 percent but below the ordinary 85 percent requirement.",
        "A request requires a medical certificate, course-wise absence statement and faculty adviser recommendation, submitted within five calendar days of return.",
        "Only a recorded approval by the Dean Academic grants condonation. Filing a request does not confer eligibility; attendance below 80 percent is outside this scheme.",
    ], ["Scope of relief", "Medical evidence", "Application forms", "Submission deadlines", "Adviser recommendations", "Document verification", "Decision meetings", "Conditional approval", "Reconsideration", "Confidential records"]),
    ("Hostel", "Chief Warden", [
        "Hostel accommodation is allotted for one academic year. Residents must sign the occupancy register and report room defects within three days of arrival.",
        "Quiet hours run from 22:00 to 06:00. Visitors must register at reception and leave by 20:00; overnight guests require prior written approval.",
        "Emergency exits must remain clear. Cooking appliances are permitted only in designated facilities and electrical faults must be reported immediately.",
    ], ["Allocation", "Room inventory", "Visitor registration", "Leave requests", "Quiet hours", "Shared facilities", "Mess services", "Maintenance", "Emergency response", "Checkout"]),
    ("Library", "Librarian", [
        "Undergraduate students may borrow four circulating books for fourteen calendar days. A single renewal is allowed unless another reader has reserved the item.",
        "Reference collections and archival materials remain in the reading room. Electronic resources are for individual academic use; bulk redistribution is prohibited.",
        "A lost item must be reported before the due date when possible. Replacement charges follow the published accession value and a written library decision.",
    ], ["Membership", "Borrowing", "Renewals", "Reservations", "Reference access", "Digital resources", "Study rooms", "Lost items", "Clearance", "Accessibility"]),
    ("Fees", "Accounts Office", [
        "Semester tuition is payable by the date on the approved fee notice. Payment must use an official channel and the receipt must identify the student and semester.",
        "An instalment request must arrive at least seven working days before the due date. Approval is recorded by the finance officer and does not waive the total fee.",
        "Refund requests require the original receipt and withdrawal acknowledgement. The applicable published refund schedule determines the amount; staff must not invent a rate.",
    ], ["Fee notices", "Payment channels", "Receipt corrections", "Instalment requests", "Scholarship adjustments", "Sponsorship", "Refund applications", "Withdrawal accounts", "Outstanding balances", "Financial clearance"]),
    ("Discipline", "Student Affairs Office", [
        "Students must treat others respectfully and must not engage in harassment, threats, violence or retaliation. Complaints may be submitted confidentially.",
        "A disciplinary notice must state the allegation and provide a reasonable opportunity to respond. The panel must disclose conflicts of interest.",
        "Any outcome must include reasons, the applicable rule and the appeal route. Interim protective arrangements are reviewed separately from a final finding.",
    ], ["Community standards", "Complaint intake", "Initial assessment", "Interim arrangements", "Notice of allegation", "Evidence access", "Hearings", "Reasoned outcomes", "Appeals", "Reintegration"]),
    ("IT and Laboratory", "Technical Services Office", [
        "Accounts are personal and passwords must not be shared. Access to institutional systems must be limited to authorised learning, teaching or administrative work.",
        "Laboratory users must complete the safety induction, wear specified protective equipment and follow supervisor instructions before operating machinery.",
        "Report a spill, injury, exposed credential or suspected compromise immediately. Preserve relevant records and avoid actions that would destroy evidence.",
    ], ["Account creation", "Access permissions", "Software licensing", "Network use", "Data handling", "Safety induction", "Equipment booking", "Hazardous materials", "Incident reporting", "Asset return"]),
    ("Miscellaneous Academic Policies", "Registrar", [
        "Changes to course registration require approval by the adviser and department before the published add-drop deadline. Students must retain the acknowledgement.",
        "Research involving human participants requires ethics approval before recruitment. Participation must be voluntary and data access must follow the approved protocol.",
        "Reasonable academic accommodations are coordinated confidentially. Approved adjustments change the access arrangement, while the stated learning outcomes remain applicable.",
    ], ["Academic advising", "Add-drop requests", "Credit transfer", "Project allocation", "Internships", "Research ethics", "Academic integrity", "Accommodations", "Student grievances", "Graduation clearance"]),
]


def generate(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with pymupdf.open() as document:
        for section_number, (topic, office, rules, procedures) in enumerate(SECTIONS, 1):
            for procedure_number, procedure in enumerate(procedures, 1):
                number = (section_number - 1) * 10 + procedure_number
                page = document.new_page(width=595, height=842)
                page.insert_text((45, 35), "RULESHIFT | FICTIONAL ACADEMIC HANDBOOK | MANUAL TEST SAMPLE", fontsize=8, color=(.25,.3,.4))
                page.insert_text((45, 67), f"{section_number:02d}. {topic}", fontsize=16, color=(.1,.2,.35))
                page.insert_text((45, 94), f"{section_number}.{procedure_number}  {procedure}", fontsize=12)
                code = f"{section_number}.{procedure_number}"
                paragraphs = [
                    f"{code}.1 Purpose and ownership. This procedure governs {procedure.lower()} within the {topic.lower()} section. The {office} is responsible for administration, communication and the final record. It applies to registered undergraduate students for the fictional academic year 2026-27.",
                    f"{code}.2 Governing requirement. {rules[0]} {rules[1]}",
                    f"{code}.3 Application and evidence. A request concerning {procedure.lower()} must identify the student, programme, semester, relevant course or facility, and the action requested. Attach the applicable register entry, notice, receipt or supporting document. The {office} records a reference number and acknowledges receipt within two working days.",
                    f"{code}.4 Review and decision. The designated officer checks the evidence against the governing requirement, records missing information and gives the applicant an opportunity to correct a factual error. {rules[2]} The ordinary target for a complete administrative request is ten working days; an explicit deadline elsewhere in this section takes precedence.",
                    f"{code}.5 Communication and appeal. Communicate the decision in writing with reasons and the relevant clause reference. An applicant may request review of a factual or procedural error within three working days. A reviewer who did not make the original decision considers the record; a pending review does not automatically suspend the original requirement.",
                    f"{code}.6 Records and boundaries. Retain the request, supporting evidence, decision, acknowledgement and review outcome in the authorised record system. Restrict access to staff with a legitimate role. This procedure for {procedure.lower()} does not waive attendance, assessment, safety or registration requirements imposed by another applicable section.",
                    f"Control record: {office} | Reference {code} | Version 2026-DEMO\nEffective date: 1 July 2026 | Review date: 30 June 2027\nIllustrative document only: not an official institution policy or legal advice.",
                ]
                body = "\n\n".join(textwrap.fill(p, width=100) for p in paragraphs)
                space = page.insert_textbox(pymupdf.Rect(45,115,550,780), body, fontsize=9, lineheight=1.16)
                if space < 0:
                    raise ValueError(f"Text overflow on page {number}: {space}")
                page.insert_text((45,810), f"DEMONSTRATION ONLY | {topic} | Page {number} of 100", fontsize=8, color=(.25,.3,.4))
        document.set_toc([[1, topic, i * 10 + 1] for i, (topic, *_) in enumerate(SECTIONS)])
        document.set_metadata({'title':'RuleShift Academic Handbook - 100-page demonstration', 'author':'RuleShift local test data', 'subject':'Fictional mixed-topic academic policies for manual ingestion testing'})
        document.save(destination, garbage=4, deflate=True)
    return destination


if __name__ == '__main__':
    print(generate(Path(__file__).resolve().parents[1] / 'samples/policies/academic_handbook_100_pages.pdf'))
