from app.events import extract_messages


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
