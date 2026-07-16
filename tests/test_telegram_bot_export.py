from pathlib import Path

from src.telegram_bot import TelegramBot


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

    bot._send_document("123", str(Path(tmp_path) / "missing.json"))
