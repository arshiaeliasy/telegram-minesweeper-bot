"""پوشش نازک روی Telegram Bot API با کتابخانهٔ استاندارد پایتون (بدون وابستگی خارجی)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


class TelegramError(Exception):
    """خطای منطقی تلگرام (ok=false)."""

    def __init__(
        self,
        method: str,
        description: str,
        error_code: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(f"{method}: {description}")
        self.method = method
        self.description = description
        self.error_code = error_code
        self.retry_after = retry_after


class TelegramNetworkError(Exception):
    """خطای شبکه/تایم‌اوت؛ تلاش دوباره بی‌خطر است."""


class TelegramAPI:
    def __init__(
        self,
        token: str,
        api_base: str = "https://api.telegram.org",
        timeout: int = 40,
    ) -> None:
        self.token = token
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def call(self, method: str, _request_timeout: int | None = None, **params):
        """فراخوانی یک متد Bot API. مقادیر None حذف می‌شوند."""
        payload = {k: v for k, v in params.items() if v is not None}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._url(method),
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        timeout = _request_timeout or self.timeout
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            data = _maybe_json(raw)
            description = data.get("description") or raw or str(exc.reason)
            parameters = data.get("parameters") or {}
            raise TelegramError(
                method,
                description,
                data.get("error_code", exc.code),
                parameters.get("retry_after"),
            ) from None
        except urllib.error.URLError as exc:
            raise TelegramNetworkError(f"{method}: {exc.reason}") from None
        except TimeoutError:
            raise TelegramNetworkError(f"{method}: timeout") from None
        except OSError as exc:
            raise TelegramNetworkError(f"{method}: {exc}") from None

        data = _maybe_json(raw)
        if not data.get("ok"):
            raise TelegramError(method, data.get("description", "unknown error"), data.get("error_code"))
        return data.get("result")

    # ------------------------------------------------------------ متدهای پرکاربرد
    def get_me(self):
        return self.call("getMe")

    def get_chat_member(self, chat_id, user_id):
        """وضعیت عضویت یک کاربر در گروه (برای بررسی مدیر بودن)."""
        return self.call("getChatMember", chat_id=chat_id, user_id=user_id)

    def delete_webhook(self, drop_pending_updates: bool = False):
        return self.call("deleteWebhook", drop_pending_updates=drop_pending_updates)

    def get_updates(
        self,
        offset: int | None = None,
        timeout: int = 25,
        allowed_updates: tuple[str, ...] = ("message", "callback_query"),
    ):
        return self.call(
            "getUpdates",
            offset=offset,
            timeout=timeout,
            allowed_updates=list(allowed_updates),
            _request_timeout=timeout + 15,
        )

    def send_message(self, chat_id, text, **kwargs):
        return self.call(
            "sendMessage",
            chat_id=chat_id,
            text=text,
            parse_mode=kwargs.pop("parse_mode", "HTML"),
            link_preview_options={"is_disabled": True},
            **kwargs,
        )

    def edit_message_text(self, chat_id, message_id, text, **kwargs):
        return self.call(
            "editMessageText",
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=kwargs.pop("parse_mode", "HTML"),
            link_preview_options={"is_disabled": True},
            **kwargs,
        )

    def answer_callback_query(self, callback_query_id, text: str | None = None, show_alert: bool = False):
        return self.call(
            "answerCallbackQuery",
            callback_query_id=callback_query_id,
            text=text or None,
            show_alert=show_alert or None,
        )


def _maybe_json(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}
