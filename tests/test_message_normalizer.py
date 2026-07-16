from copy import deepcopy

from app.services.message_normalizer import normalize_evolution_message


def test_normalizes_conversation_message() -> None:
    message = normalize_evolution_message(
        _payload_with_message({"conversation": "Quero marcar um corte"})
    )

    assert message.message_type == "text"
    assert message.text == "Quero marcar um corte"
    assert message.processable is True


def test_normalizes_extended_text_message() -> None:
    message = normalize_evolution_message(
        _payload_with_message(
            {"extendedTextMessage": {"text": "Gostaria de marcar amanhã"}}
        )
    )

    assert message.message_type == "text"
    assert message.text == "Gostaria de marcar amanhã"
    assert message.processable is True


def test_normalizes_audio_message() -> None:
    message = normalize_evolution_message(
        _payload_with_message({"audioMessage": {"mimetype": "audio/ogg"}})
    )

    assert message.message_type == "audio"
    assert message.media_mimetype == "audio/ogg"
    assert message.processable is True


def test_normalizes_image_caption() -> None:
    message = normalize_evolution_message(
        _payload_with_message(
            {"imageMessage": {"caption": "Este corte", "mimetype": "image/jpeg"}}
        )
    )

    assert message.message_type == "image"
    assert message.text == "Este corte"
    assert message.media_mimetype == "image/jpeg"
    assert message.processable is True


def test_normalizes_video_caption() -> None:
    message = normalize_evolution_message(
        _payload_with_message(
            {"videoMessage": {"caption": "Assim", "mimetype": "video/mp4"}}
        )
    )

    assert message.message_type == "video"
    assert message.text == "Assim"
    assert message.media_mimetype == "video/mp4"
    assert message.processable is True


def test_normalizes_document_message() -> None:
    message = normalize_evolution_message(
        _payload_with_message({"documentMessage": {"mimetype": "application/pdf"}})
    )

    assert message.message_type == "document"
    assert message.media_mimetype == "application/pdf"
    assert message.processable is True


def test_normalizes_sticker_message_as_not_processable() -> None:
    message = normalize_evolution_message(
        _payload_with_message({"stickerMessage": {"mimetype": "image/webp"}})
    )

    assert message.message_type == "sticker"
    assert message.media_mimetype == "image/webp"
    assert message.processable is False
    assert message.ignore_reason == "unsupported_message_type"


def test_ignores_messages_from_me() -> None:
    payload = _payload_with_message({"conversation": "Resposta enviada"})
    _key(payload)["fromMe"] = True

    message = normalize_evolution_message(payload)

    assert message.from_me is True
    assert message.processable is False
    assert message.ignore_reason == "from_me"


def test_ignores_group_messages() -> None:
    payload = _payload_with_message({"conversation": "Mensagem de grupo"})
    _key(payload)["remoteJid"] = "120363000000000000@g.us"

    message = normalize_evolution_message(payload)

    assert message.is_group is True
    assert message.phone is None
    assert message.processable is False
    assert message.ignore_reason == "group_message"


def test_ignores_unsupported_event() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    payload["event"] = "connection.update"

    message = normalize_evolution_message(payload)

    assert message.processable is False
    assert message.ignore_reason == "unsupported_event"


def test_accepts_uppercase_underscore_messages_upsert_event() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    payload["event"] = "MESSAGES_UPSERT"

    message = normalize_evolution_message(payload)

    assert message.event == "MESSAGES_UPSERT"
    assert message.processable is True


def test_handles_empty_payload() -> None:
    message = normalize_evolution_message({})

    assert message.event is None
    assert message.instance is None
    assert message.message_type == "unknown"
    assert message.processable is False
    assert message.ignore_reason == "unsupported_event"


def test_ignores_message_without_id() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    del _key(payload)["id"]

    message = normalize_evolution_message(payload)

    assert message.message_id is None
    assert message.processable is False
    assert message.ignore_reason == "missing_message_id"


def test_ignores_empty_text_message() -> None:
    message = normalize_evolution_message(_payload_with_message({"conversation": "   "}))

    assert message.message_type == "text"
    assert message.processable is False
    assert message.ignore_reason == "empty_text"


def test_extracts_phone_from_whatsapp_remote_jid() -> None:
    message = normalize_evolution_message(_payload_with_message({"conversation": "Oi"}))

    assert message.remote_jid == "5534999999999@s.whatsapp.net"
    assert message.phone == "5534999999999"


def test_does_not_extract_phone_from_lid_remote_jid() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    _key(payload)["remoteJid"] = "123456789@lid"

    message = normalize_evolution_message(payload)

    assert message.phone is None


def test_extracts_integer_timestamp() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    _data(payload)["messageTimestamp"] = 1_719_000_000

    message = normalize_evolution_message(payload)

    assert message.timestamp == 1_719_000_000


def test_extracts_string_timestamp() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    _data(payload)["messageTimestamp"] = "1719000000"

    message = normalize_evolution_message(payload)

    assert message.timestamp == 1_719_000_000


def test_ignores_invalid_timestamp() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    _data(payload)["messageTimestamp"] = "invalid"

    message = normalize_evolution_message(payload)

    assert message.timestamp is None


def test_ignores_unknown_message_type() -> None:
    message = normalize_evolution_message(
        _payload_with_message({"pollCreationMessage": {}})
    )

    assert message.message_type == "unknown"
    assert message.processable is False
    assert message.ignore_reason == "unsupported_message_type"


def test_does_not_modify_original_payload() -> None:
    payload = _payload_with_message({"conversation": "Oi"})
    original_payload = deepcopy(payload)

    normalize_evolution_message(payload)

    assert payload == original_payload


def _payload_with_message(message: dict[str, object]) -> dict[str, object]:
    return {
        "event": "messages.upsert",
        "instance": "turatti-barbe",
        "data": {
            "key": {
                "id": "ABC123",
                "remoteJid": "5534999999999@s.whatsapp.net",
                "fromMe": False,
            },
            "pushName": "Cliente Teste",
            "message": message,
        },
    }


def _data(payload: dict[str, object]) -> dict[str, object]:
    data = payload["data"]
    assert isinstance(data, dict)
    return data


def _key(payload: dict[str, object]) -> dict[str, object]:
    key = _data(payload)["key"]
    assert isinstance(key, dict)
    return key
