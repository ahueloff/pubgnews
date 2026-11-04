#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Best-effort article text extraction using requests + the Python stdlib."""
from html.parser import HTMLParser
import requests
import re

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
}

class ArticleParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form"}
    TEXT_TAGS = {"p", "h1", "h2", "h3", "li", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.capture_depth = 0
        self.parts = []
        self.title_parts = []
        self.in_title = False
        self.meta = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            value = attrs.get("content")
            if key and value:
                self.meta[key.lower()] = value.strip()
        if tag in self.TEXT_TAGS and self.skip_depth == 0:
            self.capture_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.in_title = False
        if tag in self.TEXT_TAGS and self.capture_depth:
            self.capture_depth -= 1

    def handle_data(self, data):
        value = re.sub(r"\s+", " ", data).strip()
        if not value:
            return
        if self.in_title:
            self.title_parts.append(value)
        if self.capture_depth and self.skip_depth == 0:
            self.parts.append(value)

def fetch_article(url, timeout=20):
    if not url:
        return {"title": "", "content": "", "image_url": "", "ok": False}
    try:
        response = requests.get(url, headers=HEADERS, timeout=timeout)
        response.raise_for_status()
        response.encoding = response.apparent_encoding or response.encoding
        parser = ArticleParser()
        parser.feed(response.text)
        content = "\n".join(parser.parts)
        # De-duplicate adjacent repeated fragments and trim navigation noise.
        lines, seen = [], set()
        for line in content.splitlines():
            line = line.strip()
            if len(line) < 18 or line in seen:
                continue
            seen.add(line)
            lines.append(line)
        content = "\n".join(lines)[:24000]
        title = parser.meta.get("og:title") or " ".join(parser.title_parts)
        image = parser.meta.get("og:image", "")
        return {"title": title, "content": content, "image_url": image, "ok": bool(content)}
    except Exception as exc:
        return {"title": "", "content": "", "image_url": "", "ok": False, "error": str(exc)}
