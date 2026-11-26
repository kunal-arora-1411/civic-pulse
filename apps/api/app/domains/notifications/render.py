"""Notification text for channels that leave the building (email, SMS, push).

The in-app inbox stores an i18n key plus `params` and lets the client render
it. An email, a text message or a push banner cannot do that, so the same
copy lives here in both launch languages, chosen by the recipient's locale.
It mirrors `notifications.messages` in `apps/web/messages/{en,hi}.json`; keep
the two in step.

Lock-screen safe (PRD §15.2): the text names references and a status, never
an address, a description, a photo or who reported what. Anything more
detailed is behind the link, which needs a sign-in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domains.notifications.models import NotificationKind

K = NotificationKind

# (title, body) per kind and language. `{status}` is filled with a label.
MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "en": {
        K.REPORT_NEW_ISSUE: (
            "Report {report} is now issue {issue}",
            "Yours is the first report of this problem. We'll keep you posted as it moves.",
        ),
        K.REPORT_LINKED: (
            "Report {report} joined issue {issue}",
            "Others reported the same problem, so your report was added to it. "
            "You'll get its updates.",
        ),
        K.ISSUE_STATUS: (
            "Issue {issue}: {status}",
            "The issue your report is on is now “{status}”.",
        ),
        K.REVIEW_TASK: (
            "Report {report} needs a duplicate decision",
            "Matching wasn't sure whether it repeats an existing issue. "
            "Open the review queue to decide.",
        ),
        K.ASSIGNMENT: (
            "Issue {issue} assigned to you",
            "Open your field work to accept it and get started.",
        ),
        K.SLA_BREACH: (
            "Issue {issue} is past its SLA",
            "It hasn't been resolved in the target time. Check who is working on it.",
        ),
    },
    "hi": {
        K.REPORT_NEW_ISSUE: (
            "रिपोर्ट {report} अब समस्या {issue} है",
            "इस समस्या की पहली रिपोर्ट आपकी है। आगे की जानकारी हम देते रहेंगे।",
        ),
        K.REPORT_LINKED: (
            "रिपोर्ट {report} समस्या {issue} से जुड़ी",
            "दूसरों ने भी यही समस्या बताई थी, इसलिए आपकी रिपोर्ट उसमें जोड़ दी गई। "
            "आपको उसकी जानकारी मिलती रहेगी।",
        ),
        K.ISSUE_STATUS: (
            "समस्या {issue}: {status}",
            "आपकी रिपोर्ट वाली समस्या अब “{status}” है।",
        ),
        K.REVIEW_TASK: (
            "रिपोर्ट {report} पर डुप्लिकेट निर्णय चाहिए",
            "मिलान तय नहीं कर सका कि यह किसी मौजूदा समस्या को दोहराती है या नहीं। "
            "निर्णय के लिए समीक्षा कतार खोलें।",
        ),
        K.ASSIGNMENT: (
            "समस्या {issue} आपको सौंपी गई",
            "स्वीकार करने और काम शुरू करने के लिए अपना फ़ील्ड काम खोलें।",
        ),
        K.SLA_BREACH: (
            "समस्या {issue} अपनी SLA समय-सीमा पार कर चुकी है",
            "यह लक्ष्य समय में हल नहीं हुई। देखें कि इस पर कौन काम कर रहा है।",
        ),
    },
}

# A second escalation reads differently (`sla_breach.body_level_2`).
SLA_LEVEL_2 = {
    "en": "It is still open well past its target. The supervisors were alerted earlier.",
    "hi": "यह अपने लक्ष्य से काफ़ी बाद भी खुली है। पर्यवेक्षकों को पहले सूचित किया जा चुका है।",
}

STATUS_LABELS = {
    "en": {
        "reported": "Reported",
        "under_review": "Under review",
        "verified": "Verified",
        "assigned": "Assigned",
        "in_progress": "In progress",
        "pending_verification": "Awaiting check",
        "resolved": "Resolved",
        "rejected": "Rejected",
        "closed": "Closed",
        "reopened": "Reopened",
    },
    "hi": {
        "reported": "दर्ज",
        "under_review": "जाँच में",
        "verified": "पुष्ट",
        "assigned": "सौंपा गया",
        "in_progress": "काम जारी",
        "pending_verification": "जाँच बाकी",
        "resolved": "हल हुआ",
        "rejected": "अस्वीकृत",
        "closed": "बंद",
        "reopened": "फिर से खुला",
    },
}

FALLBACK = {
    "en": ("Update", "Something changed. Open it for details."),
    "hi": ("अपडेट", "कुछ बदला है। विवरण के लिए खोलें।"),
}

# Footers that say why the message came and where to stop it.
EMAIL_FOOTER = {
    "en": "You receive this because of your CivicPulse notification settings. "
    "Change them on your profile: {url}",
    "hi": "यह आपको आपकी CivicPulse सूचना सेटिंग के कारण मिला है। इन्हें अपनी प्रोफ़ाइल पर बदलें: {url}",
}
GREETING = {"en": "Hello {name},", "hi": "नमस्ते {name},"}
GREETING_NAMELESS = {"en": "Hello,", "hi": "नमस्ते,"}
OPEN = {"en": "Open: {url}", "hi": "खोलें: {url}"}

PROFILE_PATH = "/profile"


@dataclass(frozen=True, slots=True)
class Rendered:
    title: str
    body: str
    url: str


def language(locale: str | None) -> str:
    return "hi" if (locale or "en").lower().startswith("hi") else "en"


class _Params(dict[str, Any]):
    # A missing placeholder renders as a dash, never a KeyError mid-dispatch.
    def __missing__(self, key: str) -> str:
        return "—"


def render(
    *,
    kind: str,
    body_key: str,
    params: dict[str, Any],
    link: str | None,
    locale: str | None,
    web_url: str,
) -> Rendered:
    lang = language(locale)
    values = _Params(params)
    status = str(params.get("status") or "")
    values["status"] = STATUS_LABELS[lang].get(status, status or "—")
    title, body = MESSAGES[lang].get(kind, FALLBACK[lang])
    if kind == K.SLA_BREACH and body_key.endswith("level_2"):
        body = SLA_LEVEL_2[lang]
    return Rendered(
        title=title.format_map(values),
        body=body.format_map(values),
        url=f"{web_url.rstrip('/')}{link or '/notifications'}",
    )


def sms_text(rendered: Rendered) -> str:
    """One line: who it is from, what happened, where to look."""
    return f"CivicPulse: {rendered.title}. {rendered.url}"


def email_text(rendered: Rendered, *, name: str | None, locale: str | None, web_url: str) -> str:
    lang = language(locale)
    greeting = GREETING[lang].format(name=name) if name else GREETING_NAMELESS[lang]
    profile = f"{web_url.rstrip('/')}{PROFILE_PATH}"
    return "\n".join(
        [
            greeting,
            "",
            rendered.body,
            "",
            OPEN[lang].format(url=rendered.url),
            "",
            EMAIL_FOOTER[lang].format(url=profile),
        ]
    )
