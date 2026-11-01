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
PUSH_LANG = os.getenv("PUSH_LANG", "zh-cn")

# 每次获取最新条数（上限 50）
SIZE = min(int(os.getenv("FETCH_SIZE", "10")), 50)

# 推送排除：标题包含以下任意关键词的新闻不推送
EXCLUDE_KEYWORDS = [
    "每周违规账号公示",
    "封禁公告",
    "Weekly Bans Notice",
    "Bans Notice"
]
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
if __name__ == "__main__":
    print("PUBG News: скрипт запущен")
