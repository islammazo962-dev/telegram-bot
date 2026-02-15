#!/usr/bin/env python3
"""
Secure rewritten bot.py
- Reads TELEGRAM_BOT_TOKEN from environment (or .env when python-dotenv installed)
- Keeps behavior of original: uses tiktok_fetcher (tf) and ouss modules
- Improved logging and safer defaults
"""
from __future__ import annotations

import os
import logging
import html
import time
import threading
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

# Optional: load .env if present (not required)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    # dotenv not installed — it's optional
    pass

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Local modules (keep the same names as in your repo)
import tiktok_fetcher as tf
import ouss as oouss

# CONFIG from env
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
LOG_LEVEL = os.environ.get("BOT_LOG_LEVEL", "INFO").upper()

if not BOT_TOKEN:
    raise SystemExit(
        "Missing TELEGRAM_BOT_TOKEN environment variable. "
        "Set it in your environment or create a .env file with TELEGRAM_BOT_TOKEN=your_token"
    )

# Logging
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO),
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("tiktok_merge_bot")

# Bot instance
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ---------- Safe answer for callback queries ----------
def safe_answer_callback(callback_id: str, text: Optional[str] = None,
                         show_alert: bool = False, cache_time: Optional[int] = None) -> None:
    """
    Try to answer a callback_query but ignore common "too old / invalid" errors.
    """
    try:
        kwargs: Dict[str, Any] = {}
        if text is not None:
            kwargs["text"] = text
        kwargs["show_alert"] = bool(show_alert)
        if cache_time is not None:
            kwargs["cache_time"] = int(cache_time)
        bot.answer_callback_query(callback_id, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        msg = str(e).lower()
        if ("query is too old" in msg
                or "query id is invalid" in msg
                or "query is too old and response timeout expired" in msg):
            logger.debug("Ignored stale/invalid callback_query %s: %s", callback_id, e)
        else:
            logger.exception("answer_callback_query failed (unexpected): %s", e)
    except Exception:
        logger.exception("Unexpected error when calling answer_callback_query")


# ---------- Simple TTL cache ----------
class TTLCache:
    def __init__(self, ttl: int = 600):
        self.ttl = ttl
        self._store: Dict[str, tuple] = {}

    def get(self, key: str) -> Optional[Any]:
        v = self._store.get(key)
        if not v:
            return None
        val, ts = v
        if time.time() - ts > self.ttl:
            try:
                del self._store[key]
            except KeyError:
                pass
            return None
        return val

    def set(self, key: str, val: Any) -> None:
        self._store[key] = (val, time.time())


fetch_cache = TTLCache(ttl=int(os.environ.get("FETCH_CACHE_TTL", 900)))
info_cache = TTLCache(ttl=int(os.environ.get("INFO_CACHE_TTL", 900)))
endpoint_cache = TTLCache(ttl=int(os.environ.get("ENDPOINT_CACHE_TTL", 900)))
level_cache = TTLCache(ttl=int(os.environ.get("LEVEL_CACHE_TTL", 1800)))


# ---------- Helpers ----------
def prefer(primary: Optional[Dict[str, Any]], secondary: Optional[Dict[str, Any]], key: str) -> Any:
    if not primary:
        return (secondary or {}).get(key, "")
    v = primary.get(key)
    if v is None or v == "":
        return (secondary or {}).get(key, "")
    return v


def merge_results(tf_res: Dict[str, Any] | None,
                  oouss_info: Dict[str, Any] | None,
                  endpoint_res: Dict[str, Any] | None,
                  lvl_override: Optional[str] = None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(tf_res, dict):
        merged.update(tf_res)

    merged["username"] = (prefer(tf_res, oouss_info, "username")
                          or prefer(tf_res, oouss_info, "uniqueId")
                          or merged.get("username", ""))

    merged["user_id"] = prefer(tf_res, oouss_info, "user_id") or merged.get("user_id", "")
    merged["name"] = prefer(tf_res, oouss_info, "name") or prefer(tf_res, oouss_info, "nickname") or merged.get("name", "")
    merged["bio"] = prefer(tf_res, oouss_info, "bio") or prefer(tf_res, oouss_info, "signature") or merged.get("bio", "")
    merged["avatar_larger"] = prefer(tf_res, oouss_info, "avatar_larger") or (oouss_info.get("avatar") if oouss_info else merged.get("avatar_larger", ""))
    # followers/following/likes/videos: prefer tf then oouss fields (various names tolerated)
    merged["followers"] = prefer(tf_res, oouss_info, "followers") or (oouss_info.get("followers") if oouss_info else oouss_info.get("followerCount", "") if oouss_info else merged.get("followers", ""))
    merged["following"] = prefer(tf_res, oouss_info, "following") or (oouss_info.get("following", "") if oouss_info else merged.get("following", ""))
    merged["likes"] = prefer(tf_res, oouss_info, "likes") or (oouss_info.get("like", "") if oouss_info else merged.get("likes", ""))
    merged["videos"] = prefer(tf_res, oouss_info, "videos") or (oouss_info.get("video", "") if oouss_info else merged.get("videos", ""))
    # created_date: if oouss provides a datetime under 'cdt', format it
    try:
        if prefer(tf_res, oouss_info, "created_date"):
            merged["created_date"] = prefer(tf_res, oouss_info, "created_date")
        elif oouss_info and oouss_info.get("cdt"):
            cdt = oouss_info.get("cdt")
            merged["created_date"] = cdt.strftime("%Y-%m-%d %H:%M:%S") if hasattr(cdt, "strftime") else str(cdt)
        else:
            merged["created_date"] = merged.get("created_date", "")
    except Exception:
        merged["created_date"] = merged.get("created_date", "")

    merged["country"] = prefer(tf_res, oouss_info, "country") or (oouss_info.get("country", "") if oouss_info else merged.get("country", ""))
    merged["secid"] = prefer(tf_res, oouss_info, "secid") or merged.get("secid", "")

    # Level selection
    lvl = None
    lvl_source = None
    if isinstance(tf_res, dict):
        lvl = tf_res.get("Level_Tikforge") or tf_res.get("Level_Webcast") or tf_res.get("Level") or tf_res.get("level")
        if lvl:
            lvl_source = "tiktok_fetcher"
    if not lvl and lvl_override:
        lvl = lvl_override
        lvl_source = "background_get_level"
    if lvl:
        merged["Level"] = lvl
        merged["level"] = lvl
        merged["Level_Webcast"] = merged.get("Level_Webcast") or lvl
        merged["Level_Tikforge"] = merged.get("Level_Tikforge") or lvl
        merged["Level_source"] = lvl_source or "unknown"

    # contact checks
    contact: Dict[str, Any] = {}
    if isinstance(endpoint_res, dict) and endpoint_res.get("data"):
        d = endpoint_res.get("data", {})
        contact["has_email"] = bool(d.get("has_email"))
        contact["has_mobile"] = bool(d.get("has_mobile"))
        contact["has_oauth"] = bool(d.get("has_oauth"))
        contact["has_passkey"] = bool(d.get("has_passkey"))
        contact["oauth_platforms"] = d.get("oauth_platforms", [])
    merged["contact_checks"] = contact

    return merged


def build_simple_ar_message(merged: Dict[str, Any]) -> str:
    uname = html.escape(merged.get("username", ""))
    lines = [f"🔍 معلومات حساب تيك توك — @{uname}", ""]
    if merged.get("name"):
        lines.append(f"📛 الاسم: {merged.get('name')}")
    if merged.get("bio"):
        lines.append(f"📝 البايو: {merged.get('bio')}")
    if merged.get("country"):
        lines.append(f"🌍 البلد: {merged.get('country')}")
    if merged.get("created_date"):
        lines.append(f"📅 تاريخ التسجيل: {merged.get('created_date')}")
    if merged.get("followers"):
        lines.append(f"👥 المتابعين: {merged.get('followers')}")
    if merged.get("following"):
        lines.append(f"🔁 يتابع: {merged.get('following')}")
    if merged.get("likes"):
        lines.append(f"❤️ لايكات: {merged.get('likes')}")
    if merged.get("videos"):
        lines.append(f"🎬 فيديوات: {merged.get('videos')}")
    cc = merged.get("contact_checks", {})
    if cc:
        lines.append("")
        lines.append("🔐 ملخص طرق المصادقة:")
        lines.append(f"• Email: {'✅' if cc.get('has_email') else '❌'}")
        lines.append(f"• Phone: {'✅' if cc.get('has_mobile') else '❌'}")
        lines.append(f"• OAuth: {'✅' if cc.get('has_oauth') else '❌'}")
        lines.append(f"• Passkey: {'✅' if cc.get('has_passkey') else '❌'}")
        if cc.get("oauth_platforms"):
            lines.append("• منصات OAuth: " + ", ".join(cc.get("oauth_platforms")))
    if merged.get("Level"):
        lines.append("")
        lines.append(f"⭐ مستوى الحساب: {merged.get('Level')}")
        if merged.get("Level_source"):
            lines.append(f"🔎 مصدر المستوى: {merged.get('Level_source')}")
    return "\n".join(lines)


def build_auth_message_from_endpoint(endpoint_res: Optional[Dict[str, Any]], username: str) -> str:
    if not endpoint_res or not isinstance(endpoint_res, dict):
        return "لم أتمكن من جلب بيانات المصادقة لهذا المستخدم."
    data = endpoint_res.get("data", {})
    lines = [f"🔐 كشف طرق المصادقة لحساب @{html.escape(username)}", ""]
    has_email = bool(data.get("has_email"))
    has_mobile = bool(data.get("has_mobile"))
    has_oauth = bool(data.get("has_oauth"))
    has_passkey = bool(data.get("has_passkey"))
    platforms = data.get("oauth_platforms", []) or []
    lines.append(f"• البريد الإلكتروني مرتبط: {'✅ نعم' if has_email else '❌ لا'}")
    lines.append(f"• رقم الهاتف مرتبط: {'✅ نعم' if has_mobile else '❌ لا'}")
    lines.append(f"• OAuth (حسابات خارجية): {'✅ نعم' if has_oauth else '❌ لا'}")
    if has_oauth and platforms:
        lines.append(f"  - منصات OAuth: {', '.join(platforms)}")
    lines.append(f"• Passkey (التحقق بدون كلمة مرور): {'✅ نعم' if has_passkey else '❌ لا'}")
    return "\n".join(lines)


# ---------- Handlers ----------
@bot.message_handler(commands=["start"])
def send_welcome(message) -> None:
    user = message.from_user
    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "بيك"
    full_name = html.escape(full_name)
    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("🚀 بدء الاستخدام", callback_data="start_bot"),
        InlineKeyboardButton("👤 الأدمن", url="https://t.me/w_zqw")
    )
    welcome_text = (
        "🇩🇿 أهلاً وسهلاً\n"
        f"🇩🇿 {full_name}\n\n"
        "🚀 بوت منتعاشرش dz 21\n\n"
        "🇩🇿 أرسل يوزر تيك توك\n"
        "🇩🇿 مع @ أو بدونها\n"
        "🇩🇿 انتظر 2–3 ثواني\n"
    )
    bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda call: call.data == "start_bot")
def callback_start_bot(call) -> None:
    try:
        safe_answer_callback(call.id, "أرسل الآن يوزر تيك توك (مع @ أو بدونها).")
        bot.send_message(call.message.chat.id,
                         "أرسل الآن اسم المستخدم (مثال: username أو @username)\nسأقوم بجلب معلومات الحساب خلال ثوانٍ.")
    except Exception:
        logger.exception("callback_start_bot failed")


@bot.callback_query_handler(func=lambda call: str(call.data).startswith("show_auth:"))
def callback_show_auth(call) -> None:
    try:
        safe_answer_callback(call.id, "جاري جلب بيانات المصادقة...")
        def worker() -> None:
            try:
                data = str(call.data).split(":", 1)
                if len(data) != 2:
                    safe_answer_callback(call.id, "بيانات غير صحيحة.")
                    return
                username = data[1].lstrip("@").strip()
                endpoint_res = endpoint_cache.get(username)
                if not endpoint_res:
                    try:
                        endpoint_res = oouss.find_account_end_point(username)
                        if endpoint_res:
                            endpoint_cache.set(username, endpoint_res)
                    except Exception as e:
                        logger.exception("find_account_end_point in callback worker failed: %s", e)
                        endpoint_res = None
                auth_msg = build_auth_message_from_endpoint(endpoint_res, username)
                try:
                    bot.send_message(call.message.chat.id, auth_msg)
                except Exception:
                    logger.exception("Failed to send auth_msg in callback worker")
            except Exception:
                logger.exception("callback_show_auth worker failed")
        threading.Thread(target=worker, daemon=True).start()
    except Exception:
        try:
            safe_answer_callback(call.id, "حدث خطأ أثناء جلب بيانات المصادقة.")
        except Exception:
            logger.exception("callback_show_auth final fallback failed")
        logger.exception("callback_show_auth failed")


# Performance / concurrency params
PARALLEL_TIMEOUT = int(os.environ.get("PARALLEL_TIMEOUT", 8))
GET_LEVEL_TIMEOUT = int(os.environ.get("GET_LEVEL_TIMEOUT", 5))
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", 4))


@bot.message_handler(func=lambda m: True)
def handle_username(message) -> None:
    username = message.text.strip().lstrip("@")
    if not username:
        bot.reply_to(message, "الرجاء إرسال اسم المستخدم بدون @")
        return

    status_msg = bot.reply_to(message, f"جارٍ الفحص: @{html.escape(username)} ...")

    tf_res = fetch_cache.get(username)
    oouss_info = info_cache.get(username)
    endpoint_res = endpoint_cache.get(username)
    cached_level = level_cache.get(username)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures: Dict[str, Any] = {}
        if tf_res is None:
            futures["tf"] = ex.submit(tf.fetch_and_enrich, username)
        if oouss_info is None:
            futures["info"] = ex.submit(oouss.info, username)
        if endpoint_res is None:
            futures["endpoint"] = ex.submit(oouss.find_account_end_point, username)

        for name, fut in list(futures.items()):
            try:
                res = fut.result(timeout=PARALLEL_TIMEOUT)
                if name == "tf":
                    tf_res = res
                    fetch_cache.set(username, res)
                elif name == "info":
                    oouss_info = res
                    info_cache.set(username, res)
                elif name == "endpoint":
                    endpoint_res = res
                    endpoint_cache.set(username, res)
            except Exception as e:
                logger.debug("Parallel call %s failed/timeout: %s", name, e)

        # try get level in background if missing
        lvl_from_tf = None
        if isinstance(tf_res, dict):
            lvl_from_tf = tf_res.get("Level_Tikforge") or tf_res.get("Level_Webcast") or tf_res.get("Level") or tf_res.get("level")
        lvl_override = cached_level or None
        if not lvl_from_tf and not lvl_override:
            try:
                future_lvl = ex.submit(oouss.get_level, username)
                try:
                    lvl_override = future_lvl.result(timeout=GET_LEVEL_TIMEOUT)
                    if lvl_override:
                        level_cache.set(username, lvl_override)
                        logger.info("Background get_level returned for %s: %s", username, lvl_override)
                except Exception as e:
                    logger.debug("get_level background failed/timeout: %s", e)
                    lvl_override = None
            except Exception:
                lvl_override = None

    merged = merge_results(tf_res if isinstance(tf_res, dict) else {}, 
                           oouss_info if isinstance(oouss_info, dict) else {},
                           endpoint_res if isinstance(endpoint_res, dict) else {},
                           lvl_override=lvl_override)

    logger.debug("MERGED DATA for %s: %s", username, merged)

    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔐 كشف طرق المصادقة", callback_data=f"show_auth:{username}"))
    keyboard.add(InlineKeyboardButton("👤 الأدمن", url="https://t.me/w_zqw"))

    try:
        if hasattr(tf, "build_info_message"):
            text = tf.build_info_message(merged)
            if merged.get("Level_source") and "مصدر" not in text and "Level_source" not in text:
                text += f"\n\n🔎 مصدر المستوى: {merged.get('Level_source')}"
        else:
            text = build_simple_ar_message(merged)
    except Exception:
        logger.exception("build_info_message failed, using simple message")
        text = build_simple_ar_message(merged)

    avatar = merged.get("avatar_larger") or merged.get("avatar") or None
    try:
        if avatar:
            bot.send_photo(message.chat.id, avatar, caption=text, reply_markup=keyboard)
        else:
            if len(text) > 4000:
                parts = [text[i:i+3900] for i in range(0, len(text), 3900)]
                bot.send_message(message.chat.id, parts[0], reply_markup=keyboard)
                for p in parts[1:]:
                    bot.send_message(message.chat.id, p)
            else:
                bot.send_message(message.chat.id, text, reply_markup=keyboard)
    except Exception:
        logger.exception("send message failed")
        try:
            bot.reply_to(message, text)
        except Exception:
            bot.reply_to(message, "حدث خطأ أثناء إرسال النتيجة. حاول لاحقاً.")

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception:
        pass


if __name__ == "__main__":
    logger.info("Bot started")
    # infinity_polling parameters can be tuned via env variables
    bot.infinity_polling(timeout=int(os.environ.get("POLL_TIMEOUT", 60)),
                        long_polling_timeout=int(os.environ.get("LONG_POLL_TIMEOUT", 60)))
