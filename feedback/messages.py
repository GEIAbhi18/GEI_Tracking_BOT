"""
Feedback Message Templates
==========================
All WhatsApp messages sent by the feedback bot.
"""


def message_a(client_name: str, complaint_id: str, complaint_nature: str, unit_no: str) -> str:
    return (
        f"Dear {client_name},\n\n"
        f"Your complaint *{complaint_id}* regarding *{complaint_nature}* "
        f"at *Unit {unit_no}* has been successfully resolved by the "
        f"Good Earth Facilities Team. ✅\n\n"
        f"We value your experience and would love to hear your feedback. "
        f"It will only take a minute.\n\n"
        f"Please reply *START* to begin."
    )


def question_1(complaint_id: str) -> str:
    return (
        f"*Feedback for Complaint {complaint_id}*\n\n"
        f"*Question 1 of 4*\n"
        f"How would you rate the time taken and quality of resolution "
        f"for your complaint?\n\n"
        f"Reply with a number:\n"
        f"1️⃣ - Least Satisfied\n"
        f"2️⃣\n"
        f"3️⃣\n"
        f"4️⃣\n"
        f"5️⃣ - Extremely Satisfied"
    )


def question_2() -> str:
    return (
        f"*Question 2 of 4*\n"
        f"How would you rate the professionalism of the Facility Team?\n\n"
        f"Reply with a number:\n"
        f"1️⃣ - Least Satisfied\n"
        f"2️⃣\n"
        f"3️⃣\n"
        f"4️⃣\n"
        f"5️⃣ - Extremely Satisfied"
    )


def question_3() -> str:
    return (
        f"*Question 3 of 4*\n"
        f"How satisfied are you with the overall complaint handling experience?\n\n"
        f"Reply with a number:\n"
        f"1️⃣ - Least Satisfied\n"
        f"2️⃣\n"
        f"3️⃣\n"
        f"4️⃣\n"
        f"5️⃣ - Extremely Satisfied"
    )


def question_4() -> str:
    return (
        f"*Question 4 of 4*\n"
        f"Do you have any suggestions or comments for us?\n\n"
        f"(You may type your feedback freely or reply *SKIP* to skip)"
    )


def message_b(client_name: str, complaint_id: str) -> str:
    return (
        f"🙏 *Thank You, {client_name}!*\n\n"
        f"Your feedback for complaint *{complaint_id}* has been officially "
        f"recorded by the Good Earth Team.\n\n"
        f"Your response helps us serve you better. We look forward to "
        f"continuing to provide you with the best facility management experience.\n\n"
        f"— *Good Earth Imaging Facilities Team* 🏢"
    )


def reminder_message(client_name: str, complaint_id: str) -> str:
    return (
        f"Hi {client_name}, 👋\n\n"
        f"This is a gentle reminder that your feedback for complaint "
        f"*{complaint_id}* is pending.\n\n"
        f"Your opinion matters to us! Please reply *START* whenever you are ready.\n\n"
        f"— Good Earth Facilities Team"
    )


def invalid_score_prompt(question_num: int) -> str:
    return (
        f"Please reply with a number between *1* and *5* for Question {question_num}.\n\n"
        f"1️⃣ - Least Satisfied\n"
        f"2️⃣\n"
        f"3️⃣\n"
        f"4️⃣\n"
        f"5️⃣ - Extremely Satisfied"
    )


def session_cancelled() -> str:
    return "Your feedback session has been cancelled. Thank you."


def complete_feedback_first(current_question_text: str) -> str:
    return (
        f"Please complete your feedback first.\n\n{current_question_text}"
    )
