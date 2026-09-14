from __future__ import annotations
import time
import logging
import re
import threading
from whatsapp.ux import clean_phone_number, send_interactive_buttons, send_text
from elara.auth import resolve_elara_user, is_elara_user, is_elara_admin
from elara.config import ELARA_DEPARTMENTS, DEVELOPER_PHONE, KANAV_PHONE
from facilities.auth import resolve_facilities_user
from facilities.config import BUILDING_TABS, BUILDING_ALIASES

logger = logging.getLogger(__name__)

# In-memory store for active locked team context and pending requests
_team_lock = threading.Lock()
_active_team_contexts: dict[str, dict] = {}   # sender -> {"team": "elara" | "facilities", "expires_at": float}
_pending_actions: dict[str, dict] = {}        # sender -> {"text": str, "timestamp": float}

CONTEXT_TTL_SECONDS = 900  # 15 minutes


def set_active_team(sender: str, team: str):
    """Lock team context ('elara' or 'facilities') for this sender."""
    clean_num = clean_phone_number(sender)
    with _team_lock:
        _active_team_contexts[clean_num] = {
            "team": team.lower(),
            "expires_at": time.time() + CONTEXT_TTL_SECONDS,
        }


def get_active_team(sender: str) -> str | None:
    """Get currently locked team context, if any."""
    clean_num = clean_phone_number(sender)
    with _team_lock:
        ctx = _active_team_contexts.get(clean_num)
        if not ctx:
            return None
        if time.time() > ctx.get("expires_at", 0):
            _active_team_contexts.pop(clean_num, None)
            return None
        return ctx.get("team")


def set_pending_action(sender: str, text: str):
    """Store ambiguous request while waiting for Kanav's team choice."""
    clean_num = clean_phone_number(sender)
    with _team_lock:
        _pending_actions[clean_num] = {
            "text": text,
            "timestamp": time.time(),
        }


def pop_pending_action(sender: str) -> str | None:
    """Retrieve and clear pending request for sender."""
    clean_num = clean_phone_number(sender)
    with _team_lock:
        item = _pending_actions.pop(clean_num, None)
        if item and time.time() - item.get("timestamp", 0) < 600:
            return item.get("text")
        return None


def is_dual_access_user(whatsapp_number: str) -> bool:
    """Check if user has access to BOTH Facilities and Elara Home (Kanav / Developer)."""
    clean_num = clean_phone_number(whatsapp_number)
    if clean_num in (KANAV_PHONE, DEVELOPER_PHONE):
        return True

    # Check if registered in both systems
    elara_u = resolve_elara_user(whatsapp_number)
    fac_u = resolve_facilities_user(whatsapp_number)
    if elara_u and fac_u:
        return True

    return False


def detect_team_intent_from_text(text: str) -> str | None:
    """
    Detect whether text explicitly mentions Elara Home vs Facilities.
    Returns: 'elara', 'facilities', or None (ambiguous).
    """
    clean = text.strip().lower()

    # 1. Explicit Elara Home markers
    if "elara" in clean:
        return "elara"

    # Check for the 6 canonical Elara departments
    for dept in ELARA_DEPARTMENTS:
        if dept.lower() in clean:
            return "elara"

    # 2. Explicit Facilities markers
    if "facilities" in clean or "facility" in clean:
        return "facilities"

    # Check for Facilities buildings or aliases
    for bldg in BUILDING_TABS:
        if bldg.lower() in clean:
            return "facilities"

    for alias in BUILDING_ALIASES:
        # Match whole words only for short aliases like "bay 1", "gett"
        if re.search(rf'\b{re.escape(alias)}\b', clean):
            return "facilities"

    # Facilities ref no pattern (e.g. GEBB1-001, GETT-123)
    if re.search(r'\b(gebb1|gebb2|gett|com)-\d{1,4}\b', clean, re.I):
        return "facilities"

    return None


def send_team_selection_prompt(to: str, custom_body: str | None = None):
    """
    Prompt Kanav with the exact required team selection buttons:
    "For which Team do you want to do this?"
    [Facilities Team]
    [Elara Home]
    """
    body = custom_body or "For which Team do you want to do this?"
    buttons = [
        {"id": "team_sel_facilities", "title": "Facilities Team"},
        {"id": "team_sel_elara", "title": "Elara Home"},
    ]
    return send_interactive_buttons(to, body, buttons)


def route_incoming_message(sender: str, text: str | None = None, button_id: str | None = None,
                           voice_transcript: str | None = None) -> bool:
    """
    Master router for all incoming WhatsApp messages.
    Returns True if the message was handled.
    """
    clean_num = clean_phone_number(sender)
    msg_text = voice_transcript if voice_transcript else (text or "")
    clean_msg = msg_text.strip().lower()

    elara_user = resolve_elara_user(clean_num)
    fac_user = resolve_facilities_user(clean_num)

    # ── 1. Handle Team Selection Buttons ─────────────────────────────────────
    if button_id in ("team_sel_facilities", "team_sel_elara"):
        selected_team = "facilities" if button_id == "team_sel_facilities" else "elara"
        set_active_team(clean_num, selected_team)

        pending_text = pop_pending_action(clean_num)
        if selected_team == "elara":
            from elara.flows.router import route_elara_message
            from elara.flows.home import show_elara_home
            send_text(sender, "🏠 Switched context to *Elara Home*.")
            if pending_text:
                route_elara_message(sender, text=pending_text, user=elara_user)
            else:
                show_elara_home(sender, elara_user or {"name": "Kanav", "role": "Director"})
            return True
        else:
            from facilities.flows.router import route_facilities_message
            from facilities.flows.home import show_home
            send_text(sender, "🏢 Switched context to *Facilities Team*.")
            if pending_text:
                route_facilities_message(sender, text=pending_text, user=fac_user or {})
            else:
                show_home(sender, fac_user or {"name": "Kanav", "role": "Director"})
            return True

    if button_id == "team_sel_prompt":
        send_team_selection_prompt(sender, "Which Team would you like to access?")
        return True

    # ── 2. Handle Elara-Specific Interactive Buttons ─────────────────────────
    if button_id and button_id.startswith("elara_"):
        set_active_team(clean_num, "elara")
        from elara.flows.router import route_elara_message
        route_elara_message(sender, button_id=button_id, user=elara_user)
        return True

    # ── 3. Handle Facilities-Specific Interactive Buttons ───────────────────
    if button_id and button_id.startswith("fac_"):
        set_active_team(clean_num, "facilities")
        from facilities.flows.router import route_facilities_message
        route_facilities_message(sender, button_id=button_id, user=fac_user or {})
        return True

    # ── 4. Categorize User Membership ────────────────────────────────────────

    # Category A: ELARA-ONLY USER (e.g. Rachit, Bhagwan Dass, Gaurav)
    if elara_user and (not fac_user or not fac_user.get("is_facilities_user")):
        from elara.flows.router import route_elara_message
        route_elara_message(sender, text=text, button_id=button_id, user=elara_user, voice_transcript=voice_transcript)
        return True

    # Category B: FACILITIES-ONLY USER (e.g. Anoop, Kuldeep, Vikash)
    if fac_user and fac_user.get("is_facilities_user") and not elara_user:
        from facilities.flows.router import route_facilities_message
        route_facilities_message(sender, text=text or "", button_id=button_id or "", user=fac_user or {}, voice_transcript=voice_transcript or "")
        return True

    # Category C: DUAL-ACCESS USER (Kanav Director, Developer)
    if is_dual_access_user(clean_num):
        # 1. Check if user is in an active in-flight multi-step flow
        from elara.session import get_elara_session
        from facilities.flows.router import get_session as get_fac_session

        elara_sess = get_elara_session(clean_num)
        if elara_sess and elara_sess.get("flow_state"):
            from elara.flows.router import route_elara_message
            route_elara_message(sender, text=text, button_id=button_id, user=elara_user, voice_transcript=voice_transcript)
            return True

        fac_sess = get_fac_session(clean_num)
        if fac_sess and fac_sess.get("current_flow_state"):
            from facilities.flows.router import route_facilities_message
            route_facilities_message(sender, text=text or "", button_id=button_id or "", user=fac_user or {}, voice_transcript=voice_transcript or "")
            return True

        # 2. Greeting check ("hi", "hello", "hey", "start", "menu"):
        # Explicit requirement from review:
        # "Also when kanav send hi or Hello make sure he sees for both team facilities and Elara Home both"
        greeting_words = ("hi", "hello", "hey", "start", "menu")
        if clean_msg in greeting_words:
            user_name = (elara_user or fac_user or {}).get("name", "Kanav")
            body = (
                f"👋 Hello *{user_name}*!\n\n"
                f"Which Team would you like to access today?"
            )
            send_team_selection_prompt(sender, custom_body=body)
            return True

        # 3. Explicit switch command check
        if clean_msg in ("switch team", "switch to elara", "elara home", "open elara"):
            set_active_team(clean_num, "elara")
            from elara.flows.home import show_elara_home
            show_elara_home(sender, elara_user or {"name": "Kanav", "role": "Director"})
            return True

        if clean_msg in ("switch to facilities", "facilities team", "facilities"):
            set_active_team(clean_num, "facilities")
            from facilities.flows.home import show_home
            show_home(sender, fac_user or {"name": "Kanav", "role": "Director"})
            return True

        # 4. Check if text clearly indicates a specific team
        detected_team = detect_team_intent_from_text(msg_text)
        if detected_team == "elara":
            set_active_team(clean_num, "elara")
            from elara.flows.router import route_elara_message
            route_elara_message(sender, text=text, button_id=button_id, user=elara_user, voice_transcript=voice_transcript)
            return True
        elif detected_team == "facilities":
            set_active_team(clean_num, "facilities")
            from facilities.flows.router import route_facilities_message
            route_facilities_message(sender, text=text or "", button_id=button_id or "", user=fac_user or {}, voice_transcript=voice_transcript or "")
            return True

        # 5. Check if active locked team context exists from recent operation
        active_team = get_active_team(clean_num)
        if active_team == "elara":
            from elara.flows.router import route_elara_message
            route_elara_message(sender, text=text, button_id=button_id, user=elara_user, voice_transcript=voice_transcript)
            return True
        elif active_team == "facilities":
            from facilities.flows.router import route_facilities_message
            route_facilities_message(sender, text=text or "", button_id=button_id or "", user=fac_user or {}, voice_transcript=voice_transcript or "")
            return True

        # 6. Team intent is UNCLEAR / AMBIGUOUS for Kanav/Developer:
        # Prompt Kanav: "For which Team do you want to do this?" with buttons [Facilities Team] and [Elara Home]
        logger.info(f"Ambiguous team intent from dual-access user {sender}: '{msg_text}'. Prompting team selection.")
        set_pending_action(clean_num, msg_text)
        send_team_selection_prompt(sender)
        return True

    # User is not a recognized team member of either team (guest)
    return False
