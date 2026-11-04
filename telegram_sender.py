#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Telegram sender: original media + generated infographic + long-form analysis."""
import os
import time
import requests
from article_reader import fetch_article
from ai_analyzer import analyze_news
from infographic import create_infographic

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""

def _post(method, data=None, files=None, attempts=3):
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(f"{API}/{method}", data=data, files=files, timeout=35)
            response.raise_for_status()
            result = response.json()
            if result.get("ok"):
                return result
            last_error = result.get("description", "Telegram API error")
        except Exception as exc:
            last_error = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Telegram send failed after retries: {last_error}")

def _send_text(text):
    # Telegram sendMessage limit is 4096 characters. Split on paragraph boundaries.
    chunks, current = [], ""
    for paragraph in text.split("\n"):
        candidate = (current + "\n" + paragraph).strip()
        if len(candidate) > 3900 and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        _post("sendMessage", data={"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": "true"})

def send_enhanced(news, legacy_translate):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not configured")

    url = news.get("newsUrl", "")
    article = fetch_article(url) if url else {"content": "", "ok": False}
    result = analyze_news(news, article, legacy_translate)

    original_image = news.get("imageUrl") or news.get("thumbUrl") or article.get("image_url") or ""
    infographic_path = create_infographic(news, result)

    try:
        # Keep original PUBG image and generated infographic as separate Telegram photos.
        if original_image:
            caption = f"🎮 {result['title_ru']}\nИсточник: {news.get('source') or news.get('category') or 'PUBG'}"
            _post("sendPhoto", data={"chat_id": CHAT_ID, "photo": original_image, "caption": caption[:1000]})
        with open(infographic_path, "rb") as image_file:
            _post("sendPhoto", data={"chat_id": CHAT_ID, "caption": "📊 Инфографика PUBG News Alerts 2.0"},
                  files={"photo": ("pubg_infographic.png", image_file, "image/png")})

        source = news.get("source") or news.get("category") or "PUBG"
        date = news.get("displayTime") or news.get("createdAt") or "Не указана"
        text = (
            f"🎮 {result['title_ru']}\n"
            f"📂 Категория: {result['category']}\n"
            f"🕒 Дата: {date}\n"
            f"🧠 Режим анализа: {result['mode']}\n"
            f"📄 Полный материал получен: {'да' if result['has_full_article'] else 'нет, использовано доступное описание'}\n\n"
            f"{result['analysis']}\n\n"
            f"Источник: {source}\n"
            f"Оригинал: {url or 'ссылка не предоставлена'}"
        )
        _send_text(text)
        return True
    finally:
        try:
            os.remove(infographic_path)
        except OSError:
            pass
