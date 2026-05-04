from app.events import extract_messages, is_known_non_message_envelope


def test_extract_messages_from_receive_payload() -> None:
    payload = [
        {
            "envelope": {
                "sourceNumber": "+15551234567",
                "timestamp": 1710000000000,
                "dataMessage": {
                    "message": " ping ",
                },
            }
        }
    ]

    messages = extract_messages(payload)

    assert len(messages) == 1
    assert messages[0].sender == "+15551234567"
    assert messages[0].message == "ping"
    assert messages[0].timestamp == 1710000000000


def test_extract_messages_accepts_body_field() -> None:
    payload = [
        {
            "envelope": {
                "sourceNumber": "+15551234567",
                "dataMessage": {
                    "body": "hello",
                },
            }
        }
    ]

    messages = extract_messages(payload)

    assert len(messages) == 1
    assert messages[0].message == "hello"


def test_extract_messages_from_json_rpc_sync_message() -> None:
    payload = {
        "jsonrpc": "2.0",
        "method": "receive",
        "params": {
            "result": {
                "envelope": {
                    "sourceNumber": "+15551234567",
                    "syncMessage": {
                        "sentMessage": {
                            "message": "ping",
                        }
                    },
                }
            }
        },
    }

    messages = extract_messages(payload)

    assert len(messages) == 1
    assert messages[0].message == "ping"


def test_extract_messages_ignores_non_text_payloads() -> None:
    payload = [
        {"envelope": {"sourceNumber": "+15551234567", "receiptMessage": {}}},
        {"envelope": {"sourceNumber": "+15551234567", "dataMessage": {"message": ""}}},
    ]

    assert extract_messages(payload) == []


def test_is_known_non_message_envelope_recognizes_receipts() -> None:
    item = {"envelope": {"source": "uuid", "receiptMessage": {"isDelivery": True}}}
    assert is_known_non_message_envelope(item) is True


def test_is_known_non_message_envelope_recognizes_typing_and_call() -> None:
    typing = {"envelope": {"typingMessage": {"action": "STARTED"}}}
    call = {"envelope": {"callMessage": {"offer": {}}}}
    assert is_known_non_message_envelope(typing) is True
    assert is_known_non_message_envelope(call) is True


def test_is_known_non_message_envelope_recognizes_sync_without_sent_message() -> None:
    item = {"envelope": {"syncMessage": {"readMessages": []}}}
    assert is_known_non_message_envelope(item) is True


def test_is_known_non_message_envelope_rejects_real_messages() -> None:
    data = {"envelope": {"dataMessage": {"message": "hello"}}}
    sent = {"envelope": {"syncMessage": {"sentMessage": {"message": "hello"}}}}
    assert is_known_non_message_envelope(data) is False
    assert is_known_non_message_envelope(sent) is False


def test_is_known_non_message_envelope_rejects_unknown_shapes() -> None:
    assert is_known_non_message_envelope({"envelope": {}}) is False
    assert is_known_non_message_envelope("not a dict") is False


def test_extract_messages_keeps_audio_attachment_without_text() -> None:
    payload = [
        {
            "envelope": {
                "sourceNumber": "+15551234567",
                "dataMessage": {
                    "attachments": [
                        {
                            "id": "voice-note-1",
                            "contentType": "audio/ogg",
                            "filename": "voice.ogg",
                        }
                    ],
                },
            }
        }
    ]

    messages = extract_messages(payload)

    assert len(messages) == 1
    assert messages[0].message == ""
    assert messages[0].should_reply is True
    assert messages[0].audio_attachments[0].id == "voice-note-1"
