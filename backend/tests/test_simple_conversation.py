from core.simple_conversation import simple_conversation_reply


def test_requested_greeting_works_for_each_face():
    assert "Hello, Dave" in simple_conversation_reply("say hello", "hal")
    assert "Hello, sir" in simple_conversation_reply("please say hi", "jarvis")
    assert "Hi" in simple_conversation_reply("hello", "assistant")
    assert "Hello, Dave" in simple_conversation_reply("can you say hello?", "hal")


def test_common_conversation_is_answered_without_app_or_provider_context():
    assert "operational" in simple_conversation_reply("how are you?", "hal")
    assert "J.A.R.V.I.S." in simple_conversation_reply("who are you", "jarvis")
    assert "Of course" in simple_conversation_reply("can you help me?", "assistant")


def test_real_app_questions_and_actions_are_not_intercepted():
    assert simple_conversation_reply("show the highest risk providers", "hal") is None
    assert simple_conversation_reply("draft an OIG tip for this provider", "hal") is None
