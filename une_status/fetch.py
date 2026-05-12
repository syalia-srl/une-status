"""Fetch and parse the t.me/s/ public web preview."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

import httpx
from bs4 import BeautifulSoup

from . import CHANNEL

URL = f"https://t.me/s/{CHANNEL}"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:120.0) Gecko/20100101 Firefox/120.0"


@dataclass
class RawMessage:
    id: int
    ts: str  # ISO 8601 UTC
    text: str
    has_photo: bool
    has_video: bool

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts,
            "text": self.text,
            "has_photo": self.has_photo,
            "has_video": self.has_video,
        }


def _parse_html(html: str) -> list[RawMessage]:
    soup = BeautifulSoup(html, "lxml")
    out: list[RawMessage] = []
    for bubble in soup.select(".tgme_widget_message"):
        post = bubble.get("data-post")
        if not post or "/" not in post:
            continue
        msg_id = int(post.split("/")[1])
        text_div = bubble.select_one(".tgme_widget_message_text")
        text = text_div.get_text("\n", strip=True) if text_div else ""
        time_tag = bubble.select_one("time")
        ts = time_tag.get("datetime") if time_tag else None
        if not ts:
            continue
        out.append(
            RawMessage(
                id=msg_id,
                ts=ts,
                text=text,
                has_photo=bool(bubble.select_one(".tgme_widget_message_photo_wrap")),
                has_video=bool(bubble.select_one(".tgme_widget_message_video")),
            )
        )
    return sorted(out, key=lambda m: m.id)


def fetch_page(client: httpx.Client, before: int | None = None) -> list[RawMessage]:
    """Fetch one page of the channel preview. `before` paginates backward."""
    params = {"before": before} if before else {}
    r = client.get(URL, params=params, timeout=30)
    r.raise_for_status()
    return _parse_html(r.text)


def make_client() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9,en;q=0.8"},
        follow_redirects=True,
        timeout=30,
    )


def fetch_latest() -> list[RawMessage]:
    """Fetch the latest ~20 messages."""
    with make_client() as client:
        return fetch_page(client)


def fetch_backward(start_before: int, max_pages: int = 10_000, sleep_s: float = 0.3) -> Iterable[RawMessage]:
    """Generator: paginate backward starting from `before=start_before`.

    Retries transient network errors with exponential backoff (up to 5 attempts
    per page) before giving up. Long backfills against t.me/s/ regularly hit
    `ConnectionReset`-style failures partway through.
    """
    with make_client() as client:
        oldest = start_before
        for _ in range(max_pages):
            page = None
            for attempt in range(5):
                try:
                    page = fetch_page(client, before=oldest)
                    break
                except (httpx.HTTPError, httpx.RequestError) as e:
                    wait = sleep_s * (2 ** attempt) + 1.0
                    time.sleep(wait)
                    if attempt == 4:
                        raise
            if not page:
                return
            new_oldest = page[0].id
            for m in page:
                yield m
            if new_oldest >= oldest:
                return
            oldest = new_oldest
            time.sleep(sleep_s)
