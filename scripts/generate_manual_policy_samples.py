"""Create three distinct, real academic-policy PDFs for manual UI uploads.

Only writes sample documents/facts; never connects to the app, database or AI.
Uses the existing PyMuPDF dependency. Run from the repository with:
    python scripts/generate_manual_policy_samples.py
"""
import json
from pathlib import Path
import textwrap

import pymupdf


EDITIONS = {
    50: dict(version="2025-50", attendance=75, marks=16, total=40, condonation=70,
             exam_late=30, visitor_end="20:00", books=4, loan_days=14, appeal_days=5,
             refund_days=15, decision_days=10, renewal=1, allowance="department approval"),
    75: dict(version="2026-75", attendance=80, marks=20, total=50, condonation=75,
             exam_late=20, visitor_end="19:30", books=5, loan_days=21, appeal_days=7,
             refund_days=12, decision_days=8, renewal=2, allowance="Dean approval"),
    100: dict(version="2027-100", attendance=85, marks=24, total=60, condonation=80,
              exam_late=15, visitor_end="19:00", books=6, loan_days=28, appeal_days=10,
              refund_days=10, decision_days=6, renewal=3, allowance="Academic Board approval"),
}

# Each procedure has its own substantive rule. Larger editions add procedures,
# rather than padding the PDF by copying an identical page repeatedly.
TOPICS = [
 ("Attendance", "Academic Office", [
  ("Minimum attendance and calculation", "Cancelled classes are excluded from the denominator. The ordinary threshold applies separately to each registered course; an average across courses cannot cure a shortage in one course."),
  ("Registers and corrections", "Faculty close the electronic register at the end of each teaching week. A correction must identify the class date, the disputed entry and independent evidence such as a laboratory sign-in sheet."),
  ("Approved field visits", "A curriculum-linked field visit counts as attendance only when the itinerary was approved before travel and the supervising teacher certifies participation. Private travel is not an academic visit."),
  ("Late course registration", "For an approved late admission, the register begins on the formal registration date. A student who delayed registration without approval remains responsible for sessions held before completing the form."),
  ("Attendance warning notices", "The adviser must issue a written warning when the provisional register shows a shortage. A warning supports early intervention and does not amend the eligibility threshold or guarantee condonation."),
  ("Laboratory session attendance", "A laboratory session requires participation in the safety briefing and supervised practical work. Signing a register and leaving before practical work is completed does not count as attendance."),
  ("Inter-college representation", "A student selected to represent the institution must submit the official selection letter. The sports or cultural coordinator certifies actual participation before the department updates an approved duty entry."),
  ("Accessibility arrangements", "An approved access arrangement may change how participation is recorded. The coordinator must document an equivalent supervised activity; an accommodation cannot silently create attendance entries."),
  ("Final eligibility statement", "The department issues a provisional eligibility list before examinations. The final statement must distinguish ordinary eligibility, approved condonation and unresolved attendance disputes."),
  ("Register reconciliation", "At semester close, reconcile timetable changes, cancelled sessions and duplicate entries. Retain the original export and correction log so an independent reviewer can reproduce the final percentage."),
 ]),
 ("Examinations", "Examination Office", [
  ("Entry and identity checks", "Candidates must present an admit card and college identity card. An invigilator records late arrival against the room register; arriving within the permitted window never extends the scheduled finish time."),
  ("Examination registration", "A candidate must have active course registration and meet the applicable attendance and assessment conditions. An application awaiting a decision is not equivalent to an approved examination registration."),
  ("Timetable clashes", "Report two examinations scheduled for the same sitting with both course codes. Only the Examination Office may approve an alternative sitting; students must not arrange private examinations with individual teachers."),
  ("Permitted examination materials", "The paper cover specifies permitted calculators and reference tables. Internet-enabled devices, unauthorised notes and communication with another candidate are prohibited unless an approved accommodation expressly permits a device."),
  ("Answer-book identification", "Write the candidate number on the cover and attach all supplementary sheets before submission. Do not add a personal message, identifying mark or appeal for marks inside the answer script."),
  ("Accessible examination arrangements", "The accessibility coordinator supplies approved arrangements before room allocation. A scribe must not teach, interpret questions or suggest answers; the invigilator documents the arrangement in the sitting report."),
  ("Illness during an examination", "An invigilator summons medical assistance and records the time work stopped. A medical referral does not award marks; a later special-sitting request must follow the approved examination absence procedure."),
  ("Script custody", "Two authorised staff reconcile script totals against attendance before sealing a packet. Any mismatch is recorded immediately, and custody transfers require signatures from both sending and receiving officers."),
  ("Results correction", "A correction of a transcription error requires the original mark sheet and approval trail. Academic re-evaluation is a separate process and must not be presented as clerical correction."),
  ("Revaluation and moderation", "A revaluation request identifies the paper and challenged component. An independent examiner records reasons for a change, and the board checks consistency before releasing an amended result."),
 ]),
 ("Internal Assessment", "Course Coordinator", [
  ("Internal marks eligibility", "Both the internal marks minimum and the separate attendance requirement must be satisfied. A student who meets attendance but misses the marks minimum remains ineligible on the assessment condition."),
  ("Published assessment plan", "Publish component weights and submission dates before the first assessment. Changes after work is assigned require a reasoned departmental approval and a notice giving all affected students equivalent preparation time."),
  ("Class tests", "Class tests assess the declared learning outcomes using a common marking scheme. Students must receive feedback identifying the missed criterion, rather than only a total score without explanation."),
  ("Assignment authenticity", "Group discussion is allowed when the brief permits it, but an individual submission must identify borrowed work. A suspected authenticity concern requires a documented review before any penalty is applied."),
  ("Laboratory and seminar marks", "Laboratory marks reflect preparation, safe practice, results and interpretation. Seminar marks use the published presentation rubric; attendance at a seminar alone does not earn the full component score."),
  ("Missed component assessment", "A make-up request must identify the missed test and explain the documented unavoidable absence. An approved replacement tests the same learning outcomes and does not automatically grant the original component's maximum marks."),
  ("Feedback and script access", "Allow supervised inspection of marked work without removing original scripts. Record a student's requested correction and the examiner's response so the final component total can be audited."),
  ("Moderation of marks", "A second examiner samples high, middle and low scores for consistency with the rubric. Moderation may correct inconsistent application but must not add a blanket bonus without an approved academic rationale."),
  ("Final component reconciliation", "Before submission, reconcile raw marks, approved make-up scores and documented corrections. Missing work must be labelled explicitly and must not be converted into an invented passing value."),
  ("Carry-forward of assessment", "An approved repeat registration states whether any prior component may be carried forward. Carry-forward applies only to the listed component and does not waive newly prescribed learning or practical requirements."),
 ]),
 ("Condonation", "Dean Academic", [
  ("Permitted range and approval", "Condonation is discretionary relief for a documented eligible shortage. An application does not itself establish examination eligibility, and a shortage below the permitted lower bound cannot be approved under this scheme."),
  ("Medical evidence", "A medical certificate must identify the period of illness and the issuing practitioner. The office may seek verification through an authorised confidential channel; staff must not publicly circulate a student's diagnosis."),
  ("Course-wise shortage statement", "Attach a separate calculation for every affected course showing sessions held, sessions attended and the shortage. A single aggregate percentage cannot replace course-wise evidence."),
  ("Adviser recommendation", "The adviser records the academic circumstances and checks the attendance calculation. A recommendation is evidence for the decision-maker and is not a delegated power to grant relief."),
  ("Reasoned decision", "The decision must identify each approved course and the basis for relief. It must expressly reject any ineligible course rather than using an ambiguous blanket phrase such as all subjects approved."),
  ("Document deficiencies", "A deficiency notice lists the missing document and a response date. Staff keep the request pending rather than inventing facts from incomplete evidence, and record whether the applicant supplied the missing item."),
  ("Multiple absence periods", "List distinct periods of absence separately and reconcile overlapping certificates. Duplicate medical evidence cannot be counted twice to justify a larger shortage."),
  ("Exceptional non-medical requests", "A non-medical request must cite a separately applicable institutional provision. The medical condonation range cannot be extended by renaming ordinary personal absence as an exceptional circumstance."),
  ("Review of a rejected request", "A review must identify a factual error, overlooked evidence or procedural defect. A repeated application with no new grounds does not create an automatic entitlement to a second hearing."),
  ("Confidentiality and retention", "Keep the approval order in the academic eligibility record and restrict medical attachments to designated staff. Routine class lists must show the eligibility outcome without exposing private medical details."),
 ]),
 ("Fees", "Accounts Office", [
  ("Refund processing", "The refund application must include the payment receipt, withdrawal acknowledgement and verified bank details. Processing time starts when the application is complete; the approved fee schedule determines the amount."),
  ("Payment reconciliation", "Use the student's registration number and semester when reconciling a payment. A bank transfer screenshot is supporting evidence, while the accounts ledger and bank settlement establish receipt."),
  ("Instalment arrangements", "An instalment approval states the balance, due dates and consequences of default. An informal conversation with a staff member does not amend the published payment obligation."),
  ("Scholarship adjustments", "Credit a scholarship only after receiving the sponsor's confirmed award and remittance details. A pending application may be noted but must not be recorded as money already received."),
  ("Disputed charges", "A disputed charge must be linked to the fee notice or service record on which it is based. The finance officer gives a written explanation and corrects an unsupported duplicate charge."),
  ("Sponsor billing", "A sponsor letter must identify the covered fees and validity period. Costs outside that undertaking remain payable under the normal schedule unless a separate authorised concession applies."),
  ("Security deposit release", "Release a refundable deposit after the responsible office confirms clearance. Deduct only documented liabilities, and provide an itemised statement so the student can contest an incorrect charge."),
  ("Payment fraud reports", "Report a suspected fraudulent payment link through the official accounts contact. Staff preserve the message and transaction reference and do not ask the student to share banking passwords."),
  ("Financial hardship review", "A hardship request must explain the change in circumstances and requested arrangement. The review considers available institutional support without representing an unapproved waiver as an entitlement."),
  ("Year-end accounts closure", "Reconcile student balances, refunds and suspense entries before closing the academic year. Unidentified receipts remain in suspense until evidence links them to an account."),
 ]),
 ("Hostel", "Chief Warden", [
  ("Visitors and departure time", "Visitors sign in at reception, carry identification and meet residents only in designated common areas. Overnight guests require a separate written approval; the ordinary visitor permission does not cover a stay."),
  ("Room allocation", "Allocation depends on available capacity and the published priority list. An allotted room cannot be transferred privately to another student, even if no money is exchanged."),
  ("Room inventory", "Record keys, furniture and visible defects on arrival. Photographs may support the inventory, and both the resident and hostel representative acknowledge any later replacement or repair."),
  ("Quiet hours", "Residents must avoid amplified sound and disruptive gatherings during the published night quiet period. Essential maintenance is announced in advance whenever practicable and does not create a general exception for noise."),
  ("Electrical and fire safety", "Keep escape routes clear and use cooking appliances only in designated areas. A damaged socket must be isolated by qualified staff; residents must not attempt improvised repairs."),
  ("Leave and emergency contacts", "A leave request supplies departure and expected return dates and a contact number. Updating the hostel register does not automatically excuse missed teaching sessions."),
  ("Mess complaints", "A food-service complaint identifies the meal, date and problem. The mess committee records corrective action and escalates a suspected food-safety incident immediately to the responsible health contact."),
  ("Room-change requests", "A room-change request explains the need and proposed accessibility or welfare considerations. Moving before approval may make emergency occupancy records inaccurate and is not permitted."),
  ("Maintenance access", "Staff give reasonable notice before entering for routine maintenance. Emergency entry is logged with the reason, time and staff present; personal belongings must not be searched as part of an unrelated repair."),
  ("Checkout and clearance", "Return keys and complete a joint room inspection before departure. Record damage separately from ordinary wear, and give the resident an itemised explanation of any proposed recovery."),
 ]),
 ("Library", "Librarian", [
  ("Borrowing entitlement", "The loan period begins at issue and the due date appears on the receipt. A recalled item must be returned by the notified recall date; a loan entitlement does not override a valid recall."),
  ("Renewals and reservations", "Renewal is refused when another reader has an active reservation or the item belongs to a non-renewable category. A successful online request must show a revised due date before the borrower assumes an extension."),
  ("Reference-room materials", "Reference books, rare holdings and designated examination papers remain in the supervised reading room. A photocopy or scan is subject to applicable permissions and handling restrictions."),
  ("Electronic resources", "Institutional subscriptions are for authorised individual academic use. Do not share access credentials, run bulk downloads or redistribute a publisher's collection to an external service."),
  ("Lost or damaged items", "Report a lost item promptly with its accession number where available. The librarian assesses repair or replacement using the published schedule and records the basis for any recovery."),
  ("Study-room booking", "A booking names the responsible student and intended academic activity. A room left unoccupied beyond the stated grace period may be released to another group."),
  ("Accessible library services", "Readers may request accessible formats or assisted retrieval through the designated contact. The library confirms the arrangement and handles disability information confidentially."),
  ("Inter-library requests", "An inter-library request identifies the work and purpose. The lending institution's conditions, including onsite use or shorter loan periods, remain binding on the borrower."),
  ("Research repository deposits", "A repository submission includes author permission and the supervisor's approval where required. An embargo is recorded with an end date and must not be silently removed by routine cataloguing."),
  ("Graduation library clearance", "Clearance requires returned items or an approved settlement of recorded liabilities. Staff reconcile pending returns before issuing a no-dues statement."),
 ]),
 ("Discipline", "Student Affairs Office", [
  ("Respect and prohibited conduct", "Harassment, threats, violence and retaliation are prohibited. A person may report a concern without first confronting the alleged offender, and immediate welfare assistance is separate from a disciplinary finding."),
  ("Complaint intake", "Record the alleged event, approximate time, location and available witnesses. The receiving officer explains how the complaint will be handled and avoids promising a predetermined outcome."),
  ("Notice and response", "The notice identifies the alleged conduct and applicable rule, with a reasonable opportunity to respond. A vague request to explain bad behaviour is not an adequate statement of the allegation."),
  ("Impartial hearing", "Panel members disclose conflicts and withdraw where impartiality is compromised. The hearing record distinguishes agreed facts, disputed accounts and the evidence relied upon."),
  ("Appeal grounds", "An appeal identifies a procedural defect, material error or relevant new evidence. The appeal body gives reasons for its outcome and does not treat the act of appealing as further misconduct."),
  ("Interim protective arrangements", "A temporary arrangement must address a specific safety or welfare concern and be reviewed regularly. It is not a final determination that an allegation is proved."),
  ("Witness participation", "Witnesses receive a clear explanation of the process and may identify concerns about retaliation. Staff preserve the original account and record any later clarification as a separate addition."),
  ("Proportionate outcomes", "A final outcome considers the established conduct, relevant circumstances and published sanctions. The decision states why the selected response is proportionate and identifies any support or restorative steps."),
  ("Confidential case records", "Restrict case records to those with a legitimate process role. A public class announcement must not reveal confidential allegations or medical information from the file."),
  ("Return to study", "A return plan states any approved conditions, responsible contacts and review dates. Staff distinguish a support arrangement from an additional disciplinary sanction."),
 ]),
 ("IT and Laboratory", "Technical Services", [
  ("Account access", "Accounts are personal and access is limited to authorised academic duties. Multi-factor recovery must use the service desk's identity-check process; another student's credentials cannot substitute for an unavailable account."),
  ("Software licensing", "Install software only within the institution's licence and device permissions. A licence obtained for a teaching laboratory must not be copied to a commercial or unrelated personal environment."),
  ("Safety induction", "Complete the relevant induction before using laboratory equipment. A prior induction for one laboratory does not automatically cover unfamiliar machinery, chemicals or specialist hazards in another."),
  ("Equipment booking", "A booking identifies the apparatus, trained operator and intended procedure. The supervisor may refuse an unsafe or incompatible activity even when a time slot is available."),
  ("Incident reporting", "Report an injury, spill, exposed credential or suspected compromise immediately. Preserve logs and evidence, and avoid restarting or modifying affected equipment unless safety requires it."),
  ("Research data storage", "Store restricted project data only in the approved location with access controls. A personal cloud account must not be used merely because it is more convenient for collaboration."),
  ("Chemical waste", "Label waste with its contents and hazard class before transfer to the designated collection point. Mixing unknown substances or pouring a prohibited material into a drain is not an acceptable disposal method."),
  ("Network maintenance", "Announce planned outages and preserve a rollback plan for configuration changes. Emergency work must be logged even when advance notice is not possible."),
  ("Device lending", "A loaned device is issued with an inventory and return date. Report loss promptly, remove personal data on return using the approved process and do not erase institutional asset records."),
  ("Project decommissioning", "At project closure, revoke temporary accounts, archive approved records and return equipment. Data requiring retention must not be destroyed as part of routine account cleanup."),
 ]),
 ("Miscellaneous Academic Policies", "Registrar", [
  ("Academic advising", "An adviser helps students plan a programme consistent with prerequisites and credit limits. Advice must identify when a formal approval is still required; an informal plan is not itself a registration change."),
  ("Course add-drop", "An add-drop request identifies the course, proposed change and effect on the study plan. The department checks prerequisites and timetable conflicts before forwarding a decision to the registry."),
  ("Credit transfer", "A transfer request includes the originating institution's transcript and course outcomes. Credit is granted only after equivalence review and must identify the specific requirement it satisfies."),
  ("Research ethics", "Obtain ethics approval before recruiting human participants or collecting covered data. A supervisor's encouragement is not a substitute for approval, and material protocol changes require review."),
  ("Accessible learning", "An access plan records agreed adjustments and responsible contacts without unnecessary disclosure of medical details. Adjustments support access while preserving the stated learning outcomes."),
  ("Internship approval", "An internship proposal names the host, supervisor, duties and assessment evidence. Obtain academic approval before treating a placement as credit-bearing work."),
  ("Project supervision", "Record the agreed project scope, meeting schedule and assessment milestones. A major scope change must consider feasibility and resource needs before the revised plan is approved."),
  ("Academic integrity", "Attribute sources and distinguish individual from permitted collaborative work. A concern about plagiarism requires a fair review of evidence, including the assignment instructions and the student's response."),
  ("Student grievances", "A grievance should identify the decision or service issue and the remedy sought. The receiving office routes it to an appropriate reviewer and records reasons if a different process applies."),
  ("Graduation clearance", "Graduation clearance reconciles credits, approved results and outstanding institutional requirements. A missing administrative record must be investigated rather than replaced with an assumed completion entry."),
 ]),
]


CASES = [
 ["A timetable export counts two cancelled lectures as classes held", "A signed laboratory sheet conflicts with the electronic register", "A field visit was approved but the participation certificate is missing", "A late admission has a formal registration date after teaching began", "A student receives a shortage warning while a correction is pending", "A learner signed the register but missed the safety briefing", "A sports selection letter covers fewer days than the claimed absence", "An approved alternative participation record was not entered", "A provisional list describes a pending request as approved", "A timetable change created duplicate register entries"],
 ["A candidate arrives inside the admission window without an admit card", "A candidate has paid fees but lacks the required internal marks", "Two registered papers appear in the same examination sitting", "A calculator has communication features absent from the permitted list", "A supplementary sheet carries no candidate number", "An approved scribe is also the student's subject tutor", "A medical incident interrupts a candidate's answer writing", "The packet contains one fewer script than the room register", "A transcribed total differs from the signed mark sheet", "A second examiner identifies inconsistent application of the rubric"],
 ["Attendance eligibility is met but the internal score is below the minimum", "An assessment weight is changed after students submit the work", "Two markers apply different criteria to the same test question", "An individual assignment reproduces unacknowledged group material", "A seminar participant asks for full marks based on presence alone", "Illness prevented attendance at one scheduled class test", "A student identifies an unmarked answer during supervised inspection", "A sample review shows one examiner used an obsolete rubric", "An approved make-up score is missing from the final component total", "A repeat candidate assumes every old assessment score carries forward"],
 ["A course shortage falls below the scheme's lower bound", "Two certificates give conflicting dates for the same illness", "An aggregate attendance figure conceals one ineligible course", "An adviser recommends relief without checking the register", "A decision letter fails to identify which courses were approved", "The application lacks a required course-wise statement", "Overlapping certificates are counted as separate absence periods", "Personal travel is presented as a medical exemption", "A review relies on evidence unavailable at the first decision", "Medical attachments were included in a general class mailing"],
 ["A refund request has a receipt but no withdrawal acknowledgement", "One transfer reference appears against two student accounts", "An instalment plan was discussed but never approved in writing", "A scholarship applicant records an expected award as paid", "The ledger contains two charges for the same service", "A sponsor covers tuition but the invoice includes hostel fees", "A deposit deduction has no matching damage assessment", "A student receives a payment link from an unverified sender", "A family income change affects the approved payment schedule", "A bank receipt remains unidentified at the year-end cut-off"],
 ["A daytime visitor asks to remain overnight", "Two residents privately exchange allocated rooms", "A defect appears on an arrival photograph but not the inventory", "A shared-space gathering continues during quiet hours", "A portable appliance is connected to a damaged socket", "A leave entry is mistaken for academic attendance permission", "Several residents report illness after the same meal", "A resident moves before the room-change decision", "Staff need emergency access during a water leak", "The checkout report treats ordinary wear as new damage"],
 ["A borrowed title is recalled before its original due date", "A renewal request conflicts with another reader's reservation", "A reader asks to take an archival volume offsite", "A subscription account shows automated bulk downloads", "A borrower returns an item with pre-existing damage", "A booked study room remains unoccupied", "A reader needs an accessible version of a prescribed text", "An external lender imposes an onsite-use restriction", "A thesis deposit has an approved publication embargo", "A recently returned book still appears as outstanding"],
 ["A student reports threats and requests immediate welfare support", "A complaint identifies an event but no exact time", "A notice uses a vague allegation without naming the applicable rule", "A panel member supervised a key witness", "An appeal presents material evidence not previously available", "An interim restriction continues without its scheduled review", "A witness asks to correct an earlier account", "Two cases with different circumstances receive an identical unexplained sanction", "A confidential allegation is circulated on a public class channel", "A return-to-study support plan is described as a further penalty"],
 ["A learner asks a colleague to share a laboratory login", "A teaching licence is proposed for an external commercial project", "A trained user moves to a laboratory with unfamiliar hazards", "A reserved instrument is unsuitable for the proposed operation", "A suspected breach coincides with missing device logs", "A project exports restricted data to a personal cloud folder", "A waste container has no content or hazard label", "An urgent network change bypasses the normal maintenance window", "A borrowed laptop is lost before its return date", "A closed project still has active temporary accounts"],
 ["An informal study plan conflicts with a course prerequisite", "A requested course addition creates a timetable clash", "A transfer syllabus has a similar title but different learning outcomes", "Participant recruitment began before ethics approval", "A learning adjustment was communicated without its confidentiality restrictions", "A placement started before academic approval for credit", "A project scope change requires resources not yet allocated", "An assignment permits collaboration but requires individual attribution", "A service complaint has been sent to the wrong institutional process", "An otherwise eligible graduate has an unresolved administrative record"],
]


def facts_for(edition):
    e = edition
    return {
        "Attendance": f"The ordinary minimum attendance is {e['attendance']} percent in each course.",
        "Examinations": f"Examination entry closes {e['exam_late']} minutes after the published start time.",
        "Internal Assessment": f"The internal assessment minimum is {e['marks']} marks out of {e['total']}.",
        "Condonation": f"Medical condonation may be considered from {e['condonation']} percent to below {e['attendance']} percent attendance, subject to recorded {e['allowance']}.",
        "Fees": f"Complete refund applications are processed within {e['refund_days']} working days.",
        "Hostel": f"Ordinary hostel visitors must leave by {e['visitor_end']}; overnight stays require separate written approval.",
        "Library": f"Undergraduate students may borrow {e['books']} books for {e['loan_days']} calendar days, with at most {e['renewal']} renewals when no reservation is pending.",
        "Discipline": f"A disciplinary appeal must be filed within {e['appeal_days']} working days after the written decision is received.",
        "IT and Laboratory": f"A temporary laboratory account expires after {e['loan_days']} calendar days unless the project supervisor renews access in writing.",
        "Miscellaneous Academic Policies": f"A complete credit-transfer application should receive a decision within {e['decision_days']} working days after equivalence review begins.",
    }


def generate(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for count, edition in EDITIONS.items():
        filename = f"academic_policy_{count}_pages.pdf"
        facts = facts_for(edition)
        contents = []
        page_number = 0
        source_facts = {}
        with pymupdf.open() as doc:
            for topic_index, (topic, office, procedures) in enumerate(TOPICS):
                size = 5 if count == 50 else (8 if topic_index % 2 == 0 else 7) if count == 75 else 10
                start_page = page_number + 1
                contents.append([1, topic, start_page])
                source_facts[topic] = dict(page=start_page, fact=facts[topic])
                for number, (title, rule) in enumerate(procedures[:size], 1):
                    page_number += 1
                    code = f"{topic_index + 1}.{number}"
                    page = doc.new_page(width=595, height=842)
                    page.insert_text((45, 32), f"RULESHIFT MANUAL TEST | FICTIONAL POLICY | VERSION {edition['version']}", fontsize=8, color=(.25,.3,.4))
                    page.insert_text((45, 65), f"{topic_index + 1:02d}. {topic}", fontsize=15, color=(.1,.2,.35))
                    page.insert_text((45, 92), f"{code}  {title}", fontsize=12)
                    governing = facts[topic] if number == 1 else f"This procedure is administered by the {office} under the {topic.lower()} section."
                    paragraphs = [
                        f"Clause {code}.1 - Governing rule. {governing} {rule}",
                        f"Clause {code}.2 - Worked review case. {CASES[topic_index][number - 1]}. The {office} must resolve the specific discrepancy using the governing rule above. Preserve the original evidence, identify what remains disputed and communicate the reasoned result. An informal assurance cannot replace the required record or permission.",
                        f"Clause {code}.3 - Administration in this edition. Version {edition['version']} assigns this procedure reference {count}-{topic_index + 1:02d}-{number:02d}. A complete request normally receives an administrative response within {edition['decision_days']} working days. An explicit subject-specific deadline takes precedence. Exceptional changes require recorded {edition['allowance']}.",
                        f"Clause {code}.4 - Records and review. The case file must link the request concerning {title.lower()}, the source record and the decision. A factual-correction request should identify the disputed entry within {edition['appeal_days']} working days of notification, subject to any specific appeal provision. The responsible record custodian is the {office}.",
                        f"Cross-reference: apply this procedure with section {topic_index + 1}.1 of version {edition['version']}. Rules in other topics remain separate conditions. This is fictional manual-test material, not an official institution policy.",
                    ]
                    body = "\n\n".join(textwrap.fill(p, width=80) for p in paragraphs)
                    remaining = page.insert_textbox(pymupdf.Rect(45,115,550,780), body, fontsize=11, lineheight=1.2)
                    if remaining < 0:
                        raise ValueError(f"Page overflow: {filename} page {page_number}")
                    page.insert_text((45, 810), f"DEMONSTRATION ONLY | {edition['version']} | Page {page_number} of {count}", fontsize=8)
            assert len(doc) == count
            doc.set_toc(contents)
            doc.set_metadata(dict(title=f"Academic Policy - {edition['version']} - {count} pages", author="RuleShift local manual test samples"))
            doc.save(output_dir / filename, garbage=4, deflate=True)
        manifest[filename] = dict(pages=count, suggested_policy_name="Academic Policy Manual Test", suggested_version=edition['version'], facts=source_facts)
    (output_dir / "manual_test_facts.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    location = Path(__file__).resolve().parents[1] / "samples/policies"
    for name, data in generate(location).items():
        print(f"{location / name}: {data['pages']} pages")
