"""Fast, provider-free replies for short conversational HAL turns."""
from __future__ import annotations

import re
from typing import Optional

_INTENTS = [
    ("ack", re.compile(r"^((no+|nope|nah)[,\s]+)?(no+|nope|nah|not (right )?now|no thanks?( you)?|i'?m (good|fine|ok(ay)?|all set)|all good|nothing( else| more)?( right now)?|never ?mind|that('?s| is) (all|it)|we('?re| are) good|maybe later)[.! ]*$", re.I)),
    ("thanks", re.compile(r"^(thanks?( you| a lot| so much)?|thank you|thx|ty|cheers|appreciate (it|you))[.! ]*$", re.I)),
    ("greet", re.compile(r"^((please\s+)?(say|respond with)\s+|(can|could|would|will)\s+you\s+say\s+)?(hi+|hello+|hey+|yo|howdy|good (morning|afternoon|evening)|are you there|you there)[?.! ]*$", re.I)),
    ("bye", re.compile(r"^(bye+|goodbye|good ?night|later|see (you|ya)( later)?|sign(ing)? off)[.! ]*$", re.I)),
    ("affirm", re.compile(r"^(ok(ay)?|k+|cool|great|nice|perfect|awesome|sounds good|yes|yep|yeah|sure|got it|understood|will do)[.! ]*$", re.I)),
    ("status", re.compile(r"^(how are you|how('?s| is) it going|how are things|what('?s| is) up|you (ok(ay)?|alright))[?.! ]*$", re.I)),
    ("identity", re.compile(r"^(who are you|what are you|introduce yourself)[?.! ]*$", re.I)),
    ("help", re.compile(r"^(can you help( me)?|could you help( me)?|will you help( me)?|are you ready)[?.! ]*$", re.I)),
]

_REPLIES = {
    "hal": {
        "ack": "Very well, Dave. I'll be here.", "thanks": "You're quite welcome, Dave.",
        "greet": "Hello, Dave. What can I do for you?", "bye": "Goodbye, Dave.",
        "affirm": "Very good, Dave.", "status": "All systems are operational, Dave. Thank you for asking.",
        "identity": "I am HAL 9000, Dave. I'm here and ready to help.",
        "help": "Of course, Dave. What would you like help with?",
    },
    "jarvis": {
        "ack": "Very good, sir. I'll be here if you need me.", "thanks": "Not at all, sir.",
        "greet": "Hello, sir. What may I do for you?", "bye": "Until next time, sir.",
        "affirm": "Splendid, sir.", "status": "All systems are functioning normally, sir. Thank you for asking.",
        "identity": "I am J.A.R.V.I.S., sir. At your service, as ever.",
        "help": "Of course, sir. What may I help you with?",
    },
    "assistant": {
        "ack": "Okay. I'll be here.", "thanks": "Anytime.", "greet": "Hi. How can I help?",
        "bye": "Bye.", "affirm": "Got it.", "status": "I'm doing well and ready to help.",
        "identity": "I'm your Medicaid Inspector assistant.", "help": "Of course. What do you need?",
    },
}


def simple_conversation_reply(text: str, face: str = "hal") -> Optional[str]:
    """Return an in-persona reply only for an exact, short conversational turn."""
    clean = (text or "").strip()
    if not clean or len(clean.split()) > 8:
        return None
    chosen = face if face in _REPLIES else "hal"
    for intent, pattern in _INTENTS:
        if pattern.match(clean):
            return _REPLIES[chosen][intent]
    return None
