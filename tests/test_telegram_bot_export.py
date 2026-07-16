from pathlib import Path

from src.telegram_bot import TelegramBot
from src.telegram_buttons import TelegramResponse


class _Handlers:
    pass


def test_send_document_uses_only_requested_existing_file(monkeypatch, tmp_path):
    document = tmp_path / "run_summary.json"
    document.write_text("{}", encoding="utf-8")
    calls = []

    class Response:
        def raise_for_status(self):
            return None

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("src.telegram_bot.requests.post", post)
    bot = TelegramBot("token", _Handlers())

    bot._send_document("123", str(document))

    assert calls[0][0].endswith("/sendDocument")
    assert calls[0][1]["data"] == {"chat_id": "123"}
    assert calls[0][1]["files"]["document"][0] == "run_summary.json"


def test_send_document_ignores_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.telegram_bot.requests.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("request must not be sent")),
    )
    bot = TelegramBot("token", _Handlers())

    assert bot._send_document("123", str(Path(tmp_path) / "missing.json")) is False


def test_export_delivery_reports_only_successful_documents(monkeypatch, tmp_path):
    sent_path = tmp_path / "runtime_status.json"
    missing_path = tmp_path / "closed_trades.csv"
    messages = []
    documents = []
    bot = TelegramBot("token", _Handlers())

    monkeypatch.setattr(
        bot,
        "_send_message",
        lambda chat_id, text, reply_markup=None: messages.append((chat_id, text, reply_markup)),
    )

    def send_document(chat_id, path):
        documents.append((chat_id, path))
        return path == str(sent_path)

    monkeypatch.setattr(bot, "_send_document", send_document)
    response = TelegramResponse(
        "Export prepared: 2 safe file(s).",
        {"inline_keyboard": []},
        (str(sent_path), str(missing_path)),
    )

    bot._deliver_response("123", response)

    assert documents == [("123", str(sent_path)), ("123", str(missing_path))]
    assert messages[0][1] == "Export prepared: 2 safe file(s)."
    assert "Export completed." in messages[-1][1]
    assert "Sent:\n- runtime_status.json" in messages[-1][1]
    assert "Missing:\n- closed_trades.csv" in messages[-1][1]
    assert messages[-1][2] == {"inline_keyboard": []}
