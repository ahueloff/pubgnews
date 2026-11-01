#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PUBG 官网新闻/活动公告监控 → Telegram 推送
基于 yutangbb/pubg-news 改造，新增 Telegram Bot API 推送支持
GitHub Actions 定时运行，无需自建服务器
"""

import requests
import json
import os
import re
import sys
import time
import hmac
import hashlib
import base64
from datetime import datetime

# ============================================================
#  配置区（GitHub Actions 部署时全部通过 Secrets 环境变量传入）
# ============================================================

# Telegram bot credentials (configured as GitHub Actions repository secrets)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# 获取新闻语言列表（会分别保存为不同 json 文件）
LANGUAGES = ["zh-cn", "zh-tw", "en", "ko"]

# 推送通知使用的语言，设为空字符串则不推送
PUSH_LANG = os.getenv("PUSH_LANG", "en")

# 每次获取最新条数（上限 50）
SIZE = min(int(os.getenv("FETCH_SIZE", "10")), 50)

# 推送排除：标题包含以下任意关键词的新闻不推送
EXCLUDE_KEYWORDS = []
# 支持通过环境变量覆盖（用英文逗号分隔）
_env_exclude = os.getenv("EXCLUDE_KEYWORDS", "")
if _env_exclude:
    EXCLUDE_KEYWORDS = [k.strip() for k in _env_exclude.split(",") if k.strip()]

# 飞书卡片头部标题
PUSH_TITLE = os.getenv("PUSH_TITLE", "🎮 PUBG 新公告")

# 脚本所在目录
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# PUBG 官网 API（无需 API Key，公开接口）
PUBG_API = "https://api-foc.krafton.com/content/post/news"

# ============================================================
#  微博（KRAFTON_GAME 官微）配置
# ============================================================
# 是否抓取微博停机维护公告（默认开启，设为 false 关闭）
ENABLE_WEIBO = os.getenv("ENABLE_WEIBO", "true").lower() in ("1", "true", "yes")

# KRAFTON_GAME 官微 UID（https://weibo.com/u/6037906900）
WEIBO_UID = os.getenv("WEIBO_UID", "6037906900")

# 新浪移动媒体页（服务端渲染，无需登录/cookie）
WEIBO_MEDIA_URL = f"https://www.sina.cn/media/{WEIBO_UID}"

# 仅推送正文包含以下任意关键词的微博（逗号分隔）
# 默认覆盖：维护公告 / 故障公告 / 登录异常 / 服务器波动等紧急通知
_weibo_kw_env = os.getenv("WEIBO_KEYWORDS",
    "维护公告,故障公告,连接故障,登录异常,服务器异常,服务器维护,停机,热补丁")
WEIBO_KEYWORDS = [k.strip() for k in _weibo_kw_env.split(",") if k.strip()]

# 微博数据在本地缓存里使用的虚拟语言标识（对应 news_weibo.json）
WEIBO_LANG = "weibo"

# ============================================================
#  PUBG 服务器实时状态（pubg.plus）配置
# ============================================================
# 是否监控服务器状态变化（默认开启，设为 false 关闭）
ENABLE_STATUS = os.getenv("ENABLE_STATUS", "true").lower() in ("1", "true", "yes")

# pubg.plus 状态 API（前端 HMAC-SHA256 签名，密钥逆向自其 JS）
PUBG_STATUS_API = "https://apiv1.pubg.plus/status/server"
# 签名密钥（pubg.plus 前端混淆拼接，若对方更新导致 401，可通过环境变量覆盖）
PUBG_STATUS_SECRET = os.getenv("PUBG_STATUS_SECRET", "Bm4is8qQgJXdocrvobbFR7u2kh66Pu")

# 状态缓存文件（保存上次状态，用于对比变化）
STATUS_CACHE_FILE = "pubg_status_state.json"

# ============================================================
#  工具函数
# ============================================================

def log(msg):
    """打印带时间戳的日志"""
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{time_str}] {msg}", flush=True)


def gen_feishu_sign(secret, timestamp):
    """生成飞书机器人签名（开启签名校验时使用）"""
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


# ============================================================
#  PUBG 官网 API 拉取
# ============================================================

def fetch_news(lang):
    """
    调用 PUBG 官网 API 拉取指定语言的新闻列表
    返回标准化后的新闻字典列表
    """
    headers = {
        "Origin": "https://pubg.com",
        "Referer": "https://pubg.com/",
        "Service-Game": "pubg",
        "Service-Lang": lang,
        "Service-Namespace": "PUBG_OFFICIAL",
        "Service-Url": f"https://pubg.com/{lang}/news",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    params = {
        "lang": lang,
        "displayLocationType": "NORMAL",
        "size": SIZE,
        "page": 1
    }

    resp = requests.get(PUBG_API, headers=headers, params=params, timeout=30)
    resp.raise_for_status()

    posts = resp.json().get("_embedded", {}).get("post", [])
    news_items = []

    for post in posts:
        images = post.get("images") or []
        image_url = images[0].get("imageUrl", "") if images else ""
        thumb_url = images[0].get("thumbUrl", "") if images else ""

        news_items.append({
            "title": post.get("title", ""),
            "summary": post.get("summary", ""),
            "postId": post.get("postId", ""),
            "category": post.get("category", ""),
            "labels": post.get("labels", []),
            "createdAt": post.get("createdAt", ""),
            "displayTime": post.get("displayStartTime", ""),
            "imageUrl": image_url,
            "thumbUrl": thumb_url,
            "newsUrl": f"https://pubg.com/{lang}/news/{post.get('postId', '')}"
        })

    return news_items[:SIZE]


# ============================================================
#  KRAFTON 官微（sina.cn 移动页）拉取
# ============================================================

def _clean_html(text):
    """去掉 HTML 标签和微博里的零宽字符 / 多余空白"""
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def _extract_weibo_title(body):
    """
    从微博正文里提取标题：
    优先取【...】里的内容，否则取前 30 个字符
    """
    m = re.match(r"^[【\[](.+?)[】\]]", body)
    if m:
        return m.group(1).strip()
    return body[:30].strip()


def fetch_weibo():
    """
    抓取 KRAFTON_GAME 官微最新微博，过滤出含维护类关键词的条目。
    返回与官网 fetch_news 相同结构的列表，postId 用新浪详情页 oid。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/15.0 Mobile/15E148 Safari/604.1"
        )
    }
    resp = requests.get(WEIBO_MEDIA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    # 新浪移动页返回 utf-8
    html = resp.content.decode("utf-8", errors="ignore")

    # 每条微博结构：
    # <a class="post-link" href="/news/detail/{oid}.html">
    #   <article class="post"> ...
    #     <div class="time">2026-09-22 15:00<span ...>来自 ...</span></div>
    #     <div class="post-text">正文...</div>
    #   </article>
    # </a>
    pattern = re.compile(
        r'<a class="post-link" href="(/news/detail/(\d+)\.html)"[^>]*>'
        r".*?<div class=\"time\">([^<]+)<span"
        r".*?<div class=\"post-text\">(.*?)</div>",
        re.S,
    )

    news_items = []
    seen_oids = set()
    for m in pattern.finditer(html):
        href, oid, time_str, raw_body = m.groups()
        oid = oid.strip()
        if oid in seen_oids:
            continue
        seen_oids.add(oid)

        body = _clean_html(raw_body)
        # 关键词过滤：只保留维护类公告
        if not any(kw in body for kw in WEIBO_KEYWORDS):
            continue

        # 时间统一成 "YYYY-MM-DD HH:MM:SS"
        display_time = time_str.strip()
        if len(display_time) == 16:  # "2026-09-22 15:00"
            display_time += ":00"

        news_items.append({
            "title": _extract_weibo_title(body),
            "summary": body,
            "postId": oid,
            "category": "weibo",
            "labels": ["weibo"],
            "createdAt": display_time,
            "displayTime": display_time,
            "imageUrl": "",
            "thumbUrl": "",
            "newsUrl": f"https://www.sina.cn{href}",
            "source": "微博 · KRAFTON_GAME",
        })

    # 按时间倒序，最多保留 SIZE 条
    news_items.sort(key=lambda x: x["displayTime"], reverse=True)
    return news_items[:SIZE]


# ============================================================
#  PUBG 服务器实时状态（pubg.plus）
# ============================================================

def _status_sign(secret):
    """生成 pubg.plus 状态 API 的签名：HMAC-SHA256("status"+ts, secret) 前 16 hex"""
    ts = str(int(time.time()))
    msg = ("status" + ts).encode("utf-8")
    sign = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]
    return ts, sign


def fetch_pubg_status():
    """
    拉取 PUBG PC / 主机服务器实时状态。
    返回 dict: {"pc": {...}, "console": {...}, "updated_at": "..."}
    """
    ts, sign = _status_sign(PUBG_STATUS_SECRET)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Origin": "https://pubg.plus",
        "Referer": "https://pubg.plus/",
    }
    resp = requests.get(
        PUBG_STATUS_API,
        params={"ts": ts, "sign": sign},
        headers=headers,
        timeout=20,
    )
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"状态 API 返回错误：{body.get('message')}")
    return body.get("data", {})


def check_status_change(old, new):
    """
    对比新旧 PC 服务器状态，返回需要推送的消息列表。
    old 为 None/空表示首次运行，不推送任何消息（只记录基线）。

    pubg.plus 状态枚举（从实际返回反推）：
      maintenance / server_status:
        0 = 离线/异常
        1 = 正常在线
        2 = 维护中
    """
    if not old:
        return []

    messages = []
    old_p = old.get("pc") or {}
    new_p = new.get("pc") or {}
    if not new_p:
        return []

    old_m = old_p.get("maintenance")
    new_m = new_p.get("maintenance")
    old_s = old_p.get("server_status")
    new_s = new_p.get("server_status")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ts = int(time.time())

    # 只有已知枚举值才参与对比，None/异常值不触发
    valid = (0, 1, 2)

    # ---- 维护状态变化（仅在 1=正常 ↔ 2=维护中 之间切换时推送）----
    if (old_m in valid and new_m in valid
            and old_m != new_m
            and {old_m, new_m} == {1, 2}):
        if new_m == 2:
            title = "🟡 PUBG PC 服务器进入维护"
            summary = "PUBG PC 服务器已开始维护，预计维护期间无法登录/匹配。"
        else:  # new_m == 1，从维护中恢复
            title = "🟢 PUBG PC 服务器维护结束"
            summary = "PUBG PC 服务器维护已结束，可以重新启动客户端进入游戏。"
        if new_p.get("online"):
            summary += f" 当前在线人数：{new_p['online']}。"
        messages.append({
            "title": title,
            "summary": summary,
            "postId": f"status_pc_maint_{new_m}_{ts}",
            "category": "status",
            "source": "服务器状态 · pubg.plus",
            "displayTime": now_str,
            "newsUrl": "https://pubg.plus/zh-CN/status",
        })

    # ---- 连接状态变化（仅在 1=正常 ↔ 0=离线 之间切换时推送；
    #      维护期间 server_status=2 属于正常现象，不单独推送）----
    if (old_s in valid and new_s in valid
            and old_s != new_s
            and {old_s, new_s} == {0, 1}):
        if new_s == 0:
            title = "🔴 PUBG PC 服务器连接中断"
            summary = "PUBG PC 服务器连接状态异常（可能崩溃或网络波动），请稍后重试。"
        else:
            title = "🟢 PUBG PC 服务器连接恢复"
            summary = "PUBG PC 服务器连接已恢复。"
        messages.append({
            "title": title,
            "summary": summary,
            "postId": f"status_pc_conn_{new_s}_{ts}",
            "category": "status",
            "source": "服务器状态 · pubg.plus",
            "displayTime": now_str,
            "newsUrl": "https://pubg.plus/zh-CN/status",
        })

    return messages


def load_status_state():
    """读取上次保存的服务器状态"""
    filename = os.path.join(SCRIPT_DIR, STATUS_CACHE_FILE)
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def save_status_state(state):
    """保存当前 PC 服务器状态（只存对比需要的字段）"""
    filename = os.path.join(SCRIPT_DIR, STATUS_CACHE_FILE)
    pc = state.get("pc") or {}
    slim = {
        "pc": {
            "maintenance": pc.get("maintenance"),
            "server_status": pc.get("server_status"),
            "client_version": pc.get("client_version"),
            "online": pc.get("online"),
        },
        "updated_at": state.get("updated_at", ""),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(slim, f, ensure_ascii=False, indent=2)


# ============================================================
#  本地缓存（json 文件，跨运行保留已推送记录）
# ============================================================

def load_existing(lang):
    """读取已保存的新闻列表（用于对比增量）"""
    filename = os.path.join(SCRIPT_DIR, f"news_{lang}.json")
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def save_news(lang, news_items):
    """保存新闻列表到 json 文件"""
    filename = os.path.join(SCRIPT_DIR, f"news_{lang}.json")
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(news_items, f, ensure_ascii=False, indent=4)
    log(f"💾 保存 news_{lang}.json，共 {len(news_items)} 条")


def merge_news(existing, new):
    """合并新旧新闻，去重，按时间倒序，保留最新 SIZE 条"""
    existing_map = {item["postId"]: item for item in existing}
    for item in new:
        existing_map[item["postId"]] = item
    merged = list(existing_map.values())
    merged.sort(key=lambda x: x.get("displayTime", ""), reverse=True)
    return merged[:SIZE]


# ============================================================
#  Telegram 推送
# ============================================================

def translate_to_russian(text):
    """Переводит текст уведомления на русский, не меняя исходные данные в JSON.

    Сначала просит Google Translate определить язык автоматически. Если текст
    содержит латиницу и ответ не изменился, повторяет запрос как английский.
    При недоступности сервиса оставляет оригинал и пишет предупреждение в лог.
    """
    text = (text or "").strip()
    if not text:
        return text

    # Не отправляем в перевод уже русскоязычный текст без латиницы.
    has_cyrillic = bool(re.search(r"[А-Яа-яЁё]", text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_cyrillic and not has_latin:
        return text

    endpoint = "https://translate.googleapis.com/translate_a/single"
    for source_lang in ("auto", "en"):
        try:
            response = requests.get(
                endpoint,
                params={
                    "client": "gtx",
                    "sl": source_lang,
                    "tl": "ru",
                    "dt": "t",
                    "q": text,
                },
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            translated = "".join(
                part[0] for part in data[0]
                if isinstance(part, list) and part and isinstance(part[0], str)
            ).strip()
            if translated and translated != text:
                return translated
            # Если автоматическое определение вернуло оригинал, пробуем en.
        except Exception as exc:
            log(f"⚠️ Перевод на русский не удался ({source_lang}): {exc}")

    log("⚠️ Переводчик вернул исходный текст; отправляю оригинал")
    return text


def send_telegram(news):
    """Send a PUBG news or server-status notification through Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ Не настроены Telegram Bot Token или Chat ID — отправка пропущена")
        return False

    title = translate_to_russian(news.get("title", "Уведомление PUBG"))
    source = news.get("source") or news.get("category") or "PUBG"
    source = {"GitHub Actions": "GitHub Actions", "微博 · KRAFTON_GAME": "Weibo · KRAFTON_GAME", "server-status": "Статус серверов"}.get(source, translate_to_russian(source))
    summary = translate_to_russian((news.get("summary") or "").strip())
    display_time = news.get("displayTime", "")
    url = news.get("newsUrl", "")

    parts = [f"🎮 {title}", f": {source}"]
    if summary:
        parts.append(f"Описание: {summary[:1200]}")
    if display_time:
        parts.append(f"Дата: {display_time}")
    if url:
        parts.append(f"🔗 Подробнее: {url}")

    text = "\n\n".join(parts)
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        resp = requests.post(
            api_url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False},
            timeout=15,
        )
        result = resp.json()
        if resp.ok and result.get("ok") is True:
            log(f"✅ Telegram 推送成功：{title}")
            return True
        log(f"❌ Telegram 推送失败：{json.dumps(result, ensure_ascii=False)}")
        return False
    except Exception as e:
        log(f"❌ Telegram 推送异常：{e}")
        return False


def send_startup_news():
    """Стартовый отчёт отключён."""
    log("ℹ️ Стартовый отчёт отключён.")
    return True

def push_new_news(existing, new, lang):
    """
    对比新旧新闻，只推送真正新增的
    existing: 已保存的旧新闻列表
    new: 刚拉取的新新闻列表
    lang: 当前语言
    """
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("⚠️ Не настроены Telegram Bot Token или Chat ID — отправка пропущена")
        return 0

    # 官网语言按 PUSH_LANG 过滤；微博（weibo）只要开关开启就推送
    if lang == WEIBO_LANG:
        if not ENABLE_WEIBO:
            return 0
    elif lang != PUSH_LANG:
        return 0

    # 已保存的 postId 集合
    existing_ids = {item["postId"] for item in existing}
    # 已保存的最新时间（用于过滤更早的新闻）
    latest_time = existing[0].get("displayTime", "") if existing else ""

    # 按时间从旧到新排序，保证推送顺序正确
    new_sorted = sorted(new, key=lambda x: x.get("displayTime", ""))

    pushed_count = 0
    for item in new_sorted:
        post_id = item["postId"]
        title = item["title"]

        # 已推送过的跳过
        if post_id in existing_ids:
            continue

        # 时间比已保存最新的还早，跳过（防止历史新闻倒灌）
        if latest_time and item.get("displayTime", "") < latest_time:
            continue

        # 关键词过滤
        if any(kw in title for kw in EXCLUDE_KEYWORDS):
            log(f"🔇 关键词过滤，跳过：{title}")
            continue

        # 推送
        if send_telegram(item):
            pushed_count += 1
        # 无论成功失败都标记为已处理，防止失败时反复轰炸
        existing_ids.add(post_id)

    return pushed_count


# ============================================================
#  主入口
# ============================================================

def main():
    log("=" * 50)
    log("🚀 Запущен мониторинг новостей PUBG")
    log(f"📡 Язык уведомлений: {PUSH_LANG or '（未设置，不推送）'}")
    log(f"📱 Telegram: {'已配置' if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID else '未配置'}")
    log(f"📝 Исключённые ключевые слова: {EXCLUDE_KEYWORDS}")
    log(f"📱 Проверка Weibo: {'已开启（UID ' + WEIBO_UID + '，关键词=' + str(WEIBO_KEYWORDS) + '）' if ENABLE_WEIBO else '已关闭'}")
    log(f"📡 Мониторинг состояния серверов: {'已开启（pubg.plus）' if ENABLE_STATUS else '已关闭'}")
    log("=" * 50)

    total_pushed = 0

    for lang in LANGUAGES:
        log(f"\n--- Обрабатываю язык источника: {lang} ---")

        # 1. 读取本地缓存
        existing_news = load_existing(lang)
        log(f"📂 В кэше: {len(existing_news)} новостей")

        # 2. 拉取最新新闻
        try:
            new_news = fetch_news(lang)
            log(f"📡 Получено с официального сайта: {len(new_news)} новостей")
        except Exception as e:
            log(f"❌ Ошибка получения новостей ({lang}): {e}")
            continue

        if not new_news:
            log("⚠️ Новости не получены, пропускаю")
            continue

        # 3. 增量推送（仅对 PUSH_LANG 生效）
        pushed = push_new_news(existing_news, new_news, lang)
        total_pushed += pushed

        # 4. 合并并保存（无论是否推送都更新缓存）
        merged_news = merge_news(existing_news, new_news)
        save_news(lang, merged_news)

    # ---------------- 微博维护公告 ----------------
    if ENABLE_WEIBO:
        log(f"\n--- 处理微博：KRAFTON_GAME（{WEIBO_UID}）---")
        existing_weibo = load_existing(WEIBO_LANG)
        log(f"📂 微博缓存 {len(existing_weibo)} 条")

        try:
            new_weibo = fetch_weibo()
            log(f"📡 Получено уведомлений о техработах из Weibo: {len(new_weibo)}")
        except Exception as e:
            # 微博失败不影响官网主流程
            log(f"❌ Не удалось получить данные Weibo (пропускаю; сайт PUBG продолжит работать): {e}")
            new_weibo = []

        if new_weibo:
            pushed = push_new_news(existing_weibo, new_weibo, WEIBO_LANG)
            total_pushed += pushed
            merged_weibo = merge_news(existing_weibo, new_weibo)
            save_news(WEIBO_LANG, merged_weibo)

    # ---------------- 服务器实时状态（仅 PC） ----------------
    if ENABLE_STATUS:
        log(f"\n--- 处理 PC 服务器状态（pubg.plus）---")
        old_state = load_status_state()
        try:
            new_state = fetch_pubg_status()
            pc = new_state.get("pc") or {}
            log(
                f"📡 PC: maintenance={pc.get('maintenance')} "
                f"conn={pc.get('server_status')} online={pc.get('online')} "
                f"ver={pc.get('client_version')}"
            )
        except Exception as e:
            log(f"❌ Не удалось получить статус серверов (пропускаю): {e}")
            new_state = None

        if new_state:
            # 首次运行只记录基线，不推送
            if not old_state:
                log("ℹ️ Первый запуск: сохраняю исходное состояние серверов без уведомления")
            else:
                events = check_status_change(old_state, new_state)
                for ev in events:
                    if send_telegram(ev):
                        total_pushed += 1
            save_status_state(new_state)

    # 每次运行都发送一条启动检查消息，附带当前最新的 3 条新闻。
    send_startup_news()

    log("\n" + "=" * 50)
    log(f"🏁 Готово. Отправлено новых уведомлений: {total_pushed}")
    log("=" * 50)


if __name__ == "__main__":
    main()
