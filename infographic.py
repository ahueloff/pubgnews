#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a simple Telegram-ready PUBG news infographic (PNG)."""
from PIL import Image, ImageDraw, ImageFont
import os
import tempfile
import textwrap

W, H = 1200, 675

def _font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()

def _wrap(draw, text, font, max_width):
    words = (text or "").split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def create_infographic(news, analysis, output_dir=None):
    output_dir = output_dir or tempfile.gettempdir()
    os.makedirs(output_dir, exist_ok=True)
    img = Image.new("RGB", (W, H), (17, 23, 31))
    draw = ImageDraw.Draw(img)
    # Accent blocks and restrained PUBG-inspired palette.
    draw.rectangle((0, 0, W, 16), fill=(246, 170, 35))
    draw.rectangle((0, 16, 18, H), fill=(43, 190, 176))
    draw.text((64, 48), "PUBG NEWS ALERTS 2.0", font=_font(25, True), fill=(43, 190, 176))
    category = analysis.get("category", "Новости PUBG")
    draw.text((64, 96), category.upper(), font=_font(22, True), fill=(246, 170, 35))

    title = analysis.get("title_ru") or news.get("title") or "Новость PUBG"
    title_lines = _wrap(draw, title, _font(42, True), 1060)[:2]
    y = 145
    for line in title_lines:
        draw.text((64, y), line, font=_font(42, True), fill=(245, 247, 250))
        y += 55

    # Extract up to three short, factual bullets from the analysis.
    candidates = []
    for line in (analysis.get("analysis") or "").splitlines():
        line = line.strip()
        if line.startswith(("•", "-", "–")):
            value = line.lstrip("•-– ").strip()
            if len(value) > 12:
                candidates.append(value)
    if not candidates:
        candidates = ["Откройте подробное сообщение в Telegram для полного разбора."]
    y = max(y + 16, 275)
    draw.rounded_rectangle((64, y, 1136, 555), radius=22, fill=(29, 39, 49), outline=(65, 84, 96), width=2)
    draw.text((96, y + 28), "ГЛАВНОЕ", font=_font(22, True), fill=(43, 190, 176))
    bullet_y = y + 78
    for item in candidates[:3]:
        lines = _wrap(draw, item, _font(23), 970)[:2]
        draw.ellipse((98, bullet_y + 10, 110, bullet_y + 22), fill=(246, 170, 35))
        for line in lines:
            draw.text((132, bullet_y), line, font=_font(23), fill=(235, 240, 244))
            bullet_y += 32
        bullet_y += 18
        if bullet_y > 520:
            break

    date = news.get("displayTime") or news.get("createdAt") or "Дата не указана"
    source = news.get("source") or news.get("category") or "PUBG"
    footer = f"{date}  |  {source}"
    draw.text((64, 610), footer[:105], font=_font(19), fill=(165, 179, 190))
    draw.text((64, 642), "Факты сверяйте с оригинальным источником", font=_font(16), fill=(125, 143, 156))

    fd, path = tempfile.mkstemp(prefix="pubg_news_", suffix=".png", dir=output_dir)
    os.close(fd)
    img.save(path, "PNG", optimize=True)
    return path
