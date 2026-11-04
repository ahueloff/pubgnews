#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Free-first PUBG news analysis. Gemini is optional; deterministic fallback always works."""
import os
import re
import requests

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

def _translate(text, translate_func):
    text = (text or "").strip()
    if not text:
        return ""
    try:
        return translate_func(text)
    except Exception:
        return text

def _category(news):
    raw = " ".join([
        str(news.get("category", "")),
        str(news.get("title", "")),
        str(news.get("summary", ""))
    ]).lower()
    rules = [
        (("weapon", "gunplay", "оруж", "lmg", "rifle", "smg"), "Оружие и баланс"),
        (("map", "карта", "rotation", "ротац"), "Карты и ротация"),
        (("maintenance", "server", "сервер", "maintenance", "停机", "维护"), "Серверы и обслуживание"),
        (("anti-cheat", "anticheat", "cheat", "чит", "ban", "бан"), "Античит и блокировки"),
        (("store", "skin", "магазин", "скин", "коллаб"), "Магазин и косметика"),
        (("performance", "fps", "optimization", "оптимизац"), "Производительность"),
        (("dev letter", "developer", "разработчик", "roadmap", "unreal"), "Разработка PUBG"),
        (("patch", "update", "обновлен", "hotfix"), "Обновления"),
    ]
    for keys, label in rules:
        if any(k in raw for k in keys):
            return label
    return "Новости PUBG"

def _gemini_analysis(title, source_text, category):
    if not GEMINI_API_KEY:
        return None
    prompt = (
        "Ты технический редактор новостей PUBG: BATTLEGROUNDS. Отвечай по-русски. "
        "Используй только факты из предоставленного текста. Не выдумывай числа, даты, "
        "характеристики, причины или последствия. Если данных нет, прямо напиши «не указано». "
        "Отделяй подтверждённые факты от осторожных выводов. "
        "Сделай подробный разбор со структурой: Кратко; Что изменилось; Технические детали; "
        "Что это означает для игроков; Что пока неизвестно; Источник и достоверность. "
        "Если исходник короткий, не заполняй пробелы догадками.\n\n"
        f"Категория: {category}\nЗаголовок: {title}\nМатериал:\n{source_text[:18000]}"
    )
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    try:
        response = requests.post(
            url,
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1800}},
            timeout=35,
        )
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except Exception:
        # Do not log the URL or API key.
        return None

def analyze_news(news, article, translate_func):
    original_title = news.get("title", "Новость PUBG")
    original_summary = news.get("summary", "")
    article_text = (article or {}).get("content", "")
    source_text = article_text or original_summary or original_title
    category = _category(news)

    # Translate the full extracted material in chunks to avoid oversized requests.
    translated_title = _translate(original_title, translate_func)
    translated_source = _translate(source_text[:9000], translate_func)
    ai_result = _gemini_analysis(translated_title, translated_source, category)

    if ai_result:
        analysis = ai_result
        mode = "Бесплатный ИИ (Gemini free tier)"
    else:
        # Honest fallback: structured extraction, not a claim of generative AI.
        clean = re.sub(r"\s+", " ", translated_source).strip()
        sentences = re.split(r"(?<=[.!?。！？])\s+", clean)
        key_points = [s.strip() for s in sentences if len(s.strip()) > 35][:6]
        if not key_points and clean:
            key_points = [clean[:900]]
        bullets = "\n".join(f"• {p}" for p in key_points) if key_points else "• Полный текст статьи получить не удалось."
        analysis = (
            f"Кратко:\n{translated_title}\n\n"
            f"Что сообщает источник:\n{bullets}\n\n"
            "Технические детали:\n"
            "• В исходном материале отдельно не подтверждённые числовые параметры не добавлялись.\n\n"
            "Что это означает для игроков:\n"
            "• Практическое влияние зависит от конкретных изменений. Для точного вывода нужны "
            "характеристики или подробности из полного патчноута.\n\n"
            "Что пока неизвестно:\n"
            "• Дополнительные детали, отсутствующие в доступном тексте, не предполагаются."
        )
        mode = "Free Mode (без генеративного ИИ)"

    return {
        "title_ru": translated_title,
        "category": category,
        "analysis": analysis,
        "mode": mode,
        "source_text_ru": translated_source,
        "has_full_article": bool(article_text),
    }
