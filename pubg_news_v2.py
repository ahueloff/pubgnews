#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Opt-in V2 launcher. Reuses the existing parser and patches only its Telegram sender."""
import pubg_news as legacy
from telegram_sender import send_enhanced

def _send_telegram_v2(news):
    try:
        ok = send_enhanced(news, legacy.translate_to_russian)
        if ok:
            legacy.log(f"✅ V2 Telegram push: {news.get('title', '')}")
        return bool(ok)
    except Exception as exc:
        legacy.log(f"❌ V2 delivery failed: {exc}")
        return False

if __name__ == "__main__":
    legacy.send_telegram = _send_telegram_v2
    legacy.log("🚀 PUBG News Alerts 2.0 — тестовый запуск")
    legacy.main()
