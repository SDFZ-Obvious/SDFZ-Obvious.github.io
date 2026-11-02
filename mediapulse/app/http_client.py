"""Small dependency-free HTTP helper with cookies, retries and JSON decoding."""
from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import Cookie, CookieJar
from typing import Any

from .config import USER_AGENT


class ApiError(RuntimeError):
    def __init__(self, message: str, code: int | str | None = None, payload: Any = None):
        super().__init__(message)
        self.code = code
        self.payload = payload


class HttpClient:
    def __init__(self, cookie_text: str = "", headers: dict[str, str] | None = None):
        self.jar = CookieJar()
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip",
            **(headers or {}),
        }
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(),
        )
        if cookie_text:
            self.load_cookie_string(cookie_text)

    def load_cookie_string(self, text: str, domain: str = ".bilibili.com"):
        for part in (text or "").split(";"):
            if "=" not in part:
                continue
            name, value = part.strip().split("=", 1)
            if not name:
                continue
            cookie = Cookie(
                version=0, name=name, value=value, port=None, port_specified=False,
                domain=domain, domain_specified=True, domain_initial_dot=domain.startswith("."),
                path="/", path_specified=True, secure=True, expires=None, discard=False,
                comment=None, comment_url=None, rest={}, rfc2109=False,
            )
            self.jar.set_cookie(cookie)

    def cookie_string(self) -> str:
        return "; ".join(f"{c.name}={c.value}" for c in self.jar)

    def cookie_dict(self) -> dict[str, str]:
        return {c.name: c.value for c in self.jar}

    def request(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        *,
        method: str = "GET",
        data: dict[str, Any] | None = None,
        json_body: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 25,
        retries: int = 2,
        raw: bool = False,
    ) -> Any:
        if params:
            sep = "&" if "?" in url else "?"
            url = f"{url}{sep}{urllib.parse.urlencode(params, doseq=True)}"
        body = None
        req_headers = {**self.headers, **(headers or {})}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            req_headers["Content-Type"] = "application/x-www-form-urlencoded"
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
                with self.opener.open(req, timeout=timeout) as resp:
                    payload = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        payload = gzip.decompress(payload)
                    if raw:
                        return payload
                    text = payload.decode("utf-8", errors="replace")
                    if not text.strip():
                        return {}
                    return json.loads(text)
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8", errors="replace")[:300]
                except Exception:
                    pass
                last_error = ApiError(f"HTTP {exc.code}: {detail or exc.reason}", exc.code)
                if exc.code in (400, 401, 403, 404):
                    break
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last_error = ApiError(f"网络请求失败: {exc}")
            if attempt < retries:
                time.sleep(0.7 * (attempt + 1))
        raise last_error or ApiError("请求失败")

    def get_json(self, url: str, params: dict[str, Any] | None = None, **kwargs) -> dict:
        result = self.request(url, params, **kwargs)
        if not isinstance(result, dict):
            raise ApiError("接口返回格式异常")
        return result

    def post_form(self, url: str, data: dict[str, Any], **kwargs) -> dict:
        result = self.request(url, method="POST", data=data, **kwargs)
        if not isinstance(result, dict):
            raise ApiError("接口返回格式异常")
        return result
