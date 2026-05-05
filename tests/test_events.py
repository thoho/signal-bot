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


def test_signal_attachment_is_audio_recognizes_mime_and_extension() -> None:
    from app.events import SignalAttachment

    audio_mime = SignalAttachment(id="a", content_type="audio/mpeg", filename="x", raw={})
    ogg_app = SignalAttachment(id="a", content_type="application/ogg", filename="x", raw={})
    by_ext = SignalAttachment(id="a", content_type=None, filename="voice.opus", raw={})
    by_id_ext = SignalAttachment(id="voice.flac", content_type=None, filename=None, raw={})
    not_audio = SignalAttachment(id="a", content_type="image/png", filename="pic.png", raw={})

    assert audio_mime.is_audio is True
    assert ogg_app.is_audio is True
    assert by_ext.is_audio is True
    assert by_id_ext.is_audio is True
    assert not_audio.is_audio is False


def test_extract_messages_skips_non_dict_items_and_envelopes() -> None:
    payload = ["not-a-dict", 42, {"envelope": "still-not-a-dict"}]

    assert extract_messages(payload) == []


def test_extract_messages_returns_empty_for_none_or_empty() -> None:
    assert extract_messages(None) == []
    assert extract_messages([]) == []


def test_extract_messages_normalizes_single_dict_to_list() -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15551234567",
            "dataMessage": {"message": "hi"},
        }
    }

    messages = extract_messages(payload)

    assert len(messages) == 1
    assert messages[0].message == "hi"


def test_extract_messages_keeps_group_id_when_present() -> None:
    payload = [
        {
            "envelope": {
                "sourceNumber": "+15551234567",
                "dataMessage": {
                    "message": "hi team",
                    "groupInfo": {"groupId": "grp-abc"},
                },
            }
        }
    ]

    messages = extract_messages(payload)

    assert messages[0].group_id == "grp-abc"


def test_extract_messages_drops_when_sender_is_missing_or_wrong_type() -> None:
    payload = [
        {"envelope": {"dataMessage": {"message": "hi"}}},  # no source fields
        {"envelope": {"sourceNumber": 123, "dataMessage": {"message": "hi"}}},  # wrong type
    ]

    assert extract_messages(payload) == []


def test_extract_messages_uses_params_envelope_path_when_no_result() -> None:
    """JSON-RPC payloads without `result` but with `params.envelope` should work."""
    payload = {
        "params": {
            "envelope": {
                "sourceNumber": "+1",
                "dataMessage": {"message": "from params"},
            }
        }
    }

    messages = extract_messages(payload)

    assert messages[0].message == "from params"


def test_extract_attachments_skips_invalid_entries() -> None:
    payload = [
        {
            "envelope": {
                "sourceNumber": "+1",
                "dataMessage": {
                    "message": "x",
                    "attachments": [
                        "not a dict",
                        {"contentType": "audio/ogg"},  # no id
                        {"id": 123},  # id wrong type
                        {
                            "id": "ok-id",
                            "contentType": 42,  # wrong type → None
                            "filename": 123,    # wrong type → None
                        },
                    ],
                },
            }
        }
    ]

    messages = extract_messages(payload)

    assert len(messages[0].attachments) == 1
    only = messages[0].attachments[0]
    assert only.id == "ok-id"
    assert only.content_type is None
    assert only.filename is None


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
