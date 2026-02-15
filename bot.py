#!/usr/bin/env python3
# bot.py - نسخة محسّنة: تعرض كل المعلومات + زر منفصل لكشف "بيانات المصادقة"
# يكتب كل عملية بحث في ملف CSV محلي ويُنَبّّه الأدمن إن وُضع ADMIN_CHAT_ID.
# أمنياً: لا ترفع هذا الملف للتخزين العام إذا وضعت توكن حقيقي داخله. ضع التوكن محلياً فقط.

import logging
import html
import time
import threading
import os
import csv
import datetime
from typing import Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Optional: load .env locally if you want, لكن افتراضياً ستضع التوكن داخل هذا الملف كما طلبت
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# استدعاء ملفاتك المحلية - تأكد من وجود ouss.py و tiktok_fetcher.py في نفس المجلد
import tiktok_fetcher as tf
import ouss as oouss

# Logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
logger = logging.getLogger("tiktok_merge_bot")

# ----- ضع توكن البوت هنا محلياً فقط (نفس أسلوب ملفك السابق) -----
# استبدل النص داخل علامات الاقتباس بتوكن البوت الفعلي لديك، ثم شغّل الملف محلياً.
BOT_TOKEN = "8404641547:AAHUKJZRFUO9CulPjTXtakozAToR8hLi3c0"
# ---------------------------------------------------------------
if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE" or not BOT_TOKEN:
    raise SystemExit("ضع التوكن الحقيقي داخل BOT_TOKEN في هذا الملف قبل التشغيل (محلياً فقط).")

# ----- ضع هنا إيدي الأدمن أو اتركه فارغاً لتعطيل إشعارات الأدمن -----
# يمكن أن تضع chat id رقمي (الأفضل) أو username مع @ (قد يفشل إذا لم تفتح محادثة مع البوت مسبقاً)
ADMIN_CHAT_ID = "1046998555"
if ADMIN_CHAT_ID == "YOUR_ADMIN_CHAT_ID_HERE" or not ADMIN_CHAT_ID:
    ADMIN_CHAT_ID = None
# ------------------------------------------------------------------

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ------------------ إعدادات سجل البحث (قابل للتعديل) ------------------
SEARCH_LOG_PATH = os.getenv("SEARCH_LOG_PATH", "searches.csv")

# ------------------ أمان: إجابة آمنة على callback queries ------------------
def safe_answer_callback(callback_id: str, text: Optional[str] = None, show_alert: bool = False, cache_time: Optional[int] = None):
    """
    Attempt to answer a callback_query but ignore "query is too old" / "query id is invalid" errors.
    """
    try:
        kwargs = {}
        if text is not None:
            kwargs['text'] = text
        kwargs['show_alert'] = bool(show_alert)
        if cache_time is not None:
            kwargs['cache_time'] = int(cache_time)
        bot.answer_callback_query(callback_id, **kwargs)
    except telebot.apihelper.ApiTelegramException as e:
        msg = str(e).lower()
        if "query is too old" in msg or "query id is invalid" in msg or "query is too old and response timeout expired" in msg:
            logger.debug("Ignored stale/invalid callback_query %s: %s", callback_id, e)
        else:
            logger.exception("answer_callback_query failed (unexpected): %s", e)
    except Exception:
        logger.exception("Unexpected error when calling answer_callback_query")


# ------------------ كاش بسيط مع TTL في الذاكرة (آمن للـ threads) ------------------
class TTLCache:
    def __init__(self, ttl: int = 600):
        self.ttl = ttl
        self._store: Dict[str, tuple] = {}
        self._lock = threading.Lock()

    def get(self, key: str):
        with self._lock:
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

    def set(self, key: str, val):
        with self._lock:
            self._store[key] = (val, time.time())

fetch_cache = TTLCache(ttl=900)
info_cache = TTLCache(ttl=900)
endpoint_cache = TTLCache(ttl=900)
level_cache = TTLCache(ttl=1800)

# ------------------ دوال مساعدة ------------------
def prefer(primary: Dict[str, Any], secondary: Dict[str, Any], key: str):
    if not primary:
        return (secondary or {}).get(key, "")
    v = primary.get(key)
    if v is None or v == "":
        return (secondary or {}).get(key, "")
    return v

def merge_results(tf_res: Dict[str, Any], oouss_info: Dict[str, Any], endpoint_res: Dict[str, Any], lvl_override: Optional[str]=None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    if isinstance(tf_res, dict):
        merged.update(tf_res)

    merged["username"] = prefer(tf_res, oouss_info, "username") or prefer(tf_res, oouss_info, "uniqueId") or merged.get("username", "")
    merged["user_id"] = prefer(tf_res, oouss_info, "user_id") or merged.get("user_id", "")
    merged["name"] = prefer(tf_res, oouss_info, "name") or prefer(tf_res, oouss_info, "nickname") or merged.get("name", "")
    merged["bio"] = prefer(tf_res, oouss_info, "bio") or prefer(tf_res, oouss_info, "signature") or merged.get("bio", "")
    merged["avatar_larger"] = prefer(tf_res, oouss_info, "avatar_larger") or (oouss_info.get("avatar") if oouss_info else merged.get("avatar_larger",""))
    merged["followers"] = prefer(tf_res, oouss_info, "followers") or (oouss_info.get("followers") if oouss_info else (oouss_info.get("followerCount","") if oouss_info else merged.get("followers","")))
    merged["following"] = prefer(tf_res, oouss_info, "following") or (oouss_info.get("following","") if oouss_info else merged.get("following",""))
    merged["likes"] = prefer(tf_res, oouss_info, "likes") or (oouss_info.get("like","") if oouss_info else merged.get("likes",""))
    merged["videos"] = prefer(tf_res, oouss_info, "videos") or (oouss_info.get("video","") if oouss_info else merged.get("videos",""))
    merged["created_date"] = prefer(tf_res, oouss_info, "created_date") or (oouss_info.get("cdt").strftime("%Y-%m-%d %H:%M:%S") if oouss_info and oouss_info.get("cdt") else merged.get("created_date",""))
    merged["country"] = prefer(tf_res, oouss_info, "country") or (oouss_info.get("country","") if oouss_info else merged.get("country",""))
    merged["secid"] = prefer(tf_res, oouss_info, "secid") or merged.get("secid","")

    # Level: تفضيل tf_res ثم lvl_override
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

    # contact checks (من find_account_end_point)
    contact = {}
    if isinstance(endpoint_res, dict) and endpoint_res.get("data"):
        d = endpoint_res.get("data", {})
        contact["has_email"] = bool(d.get('has_email'))
        contact["has_mobile"] = bool(d.get('has_mobile'))
        contact["has_oauth"] = bool(d.get('has_oauth'))
        contact["has_passkey"] = bool(d.get('has_passkey'))
        contact["oauth_platforms"] = d.get('oauth_platforms', [])
    merged["contact_checks"] = contact

    return merged

def build_simple_ar_message(merged: Dict[str, Any]) -> str:
    uname = html.escape(merged.get("username",""))
    lines = [f"🔍 معلومات حساب تيك توك — @{uname}", ""]
    if merged.get("name"): lines.append(f"📛 الاسم: {merged.get('name')}")
    if merged.get("bio"): lines.append(f"📝 البايو: {merged.get('bio')}")
    if merged.get("country"): lines.append(f"🌍 البلد: {merged.get('country')}")
    if merged.get("created_date"): lines.append(f"📅 تاريخ التسجيل: {merged.get('created_date')}")
    if merged.get("followers"): lines.append(f"👥 المتابعين: {merged.get('followers')}")
    if merged.get("following"): lines.append(f"🔁 يتابع: {merged.get('following')}")
    if merged.get("likes"): lines.append(f"❤️ لايكات: {merged.get('likes')}")
    if merged.get("videos"): lines.append(f"🎬 فيديوات: {merged.get('videos')}")
    cc = merged.get("contact_checks", {})
    if cc:
        lines.append(""); lines.append("🔐 ملخص طرق المصادقة:")
        lines.append(f"• Email: {'✅' if cc.get('has_email') else '❌'}")
        lines.append(f"• Phone: {'✅' if cc.get('has_mobile') else '❌'}")
        lines.append(f"• OAuth: {'✅' if cc.get('has_oauth') else '❌'}")
        lines.append(f"• Passkey: {'✅' if cc.get('has_passkey') else '❌'}")
        if cc.get("oauth_platforms"):
            lines.append("• منصات OAuth: " + ", ".join(cc.get("oauth_platforms")))
    if merged.get("Level"):
        lines.append(""); lines.append(f"⭐ مستوى الحساب: {merged.get('Level')}")
        if merged.get("Level_source"): lines.append(f"🔎 مصدر المستوى: {merged.get('Level_source')}")
    return "\n".join(lines)

def build_auth_message_from_endpoint(endpoint_res: Optional[Dict[str, Any]], username: str) -> str:
    """يبني رسالة مفصّلة لطرق المصادقة بناءً على نتيجة find_account_end_point"""
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

# ------------------ سجل عمليات البحث: CSV + إشعار للأدمن ------------------
def _ensure_csv_header(path: str):
    """إنشاء الملف مع ترويسة إن لم يكن موجوداً."""
    if not os.path.exists(path):
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "requester_id", "requester_username", "searched_username", "account_name"])
        except Exception:
            logger.exception("Failed to create search log header at %s", path)

def log_search_event(requester_message, searched_username: str, account_name: Optional[str]):
    """
    يسجل السطر التالي: timestamp, requester_id, requester_username, searched_username, account_name
    ويُرسل إشعاراً للأدمن إذا تم تحديد ADMIN_CHAT_ID.
    """
    try:
        _ensure_csv_header(SEARCH_LOG_PATH)
        ts = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        requester_id = getattr(requester_message.from_user, "id", "")
        requester_un = getattr(requester_message.from_user, "username", "") or ""
        row = [ts, requester_id, requester_un, searched_username, account_name or ""]
        # اكتب إلى CSV (append)
        try:
            with open(SEARCH_LOG_PATH, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(row)
        except Exception:
            logger.exception("Failed to append search log row")

        # إرسال إشعار للأدمن في ثريد مستقل حتى لا نوقف المعالجة
        if ADMIN_CHAT_ID:
            def notify_admin():
                try:
                    admin_text = (
                        f"🔔 بحث جديد في البوت\n"
                        f"• بواسطة: {requester_un or requester_id}\n"
                        f"• يوزر البحث: @{searched_username}\n"
                        f"• اسم الحساب: {account_name or 'غير متوفر'}\n"
                        f"• الوقت (UTC): {ts}"
                    )
                    bot.send_message(ADMIN_CHAT_ID, admin_text)
                except Exception:
                    logger.exception("Failed to notify admin about search event")
            threading.Thread(target=notify_admin, daemon=True).start()

    except Exception:
        logger.exception("log_search_event failed")


# ------------------ Handlers ------------------
@bot.message_handler(commands=['start'])
def send_welcome(message):
    user = message.from_user
    full_name = " ".join(filter(None, [user.first_name, user.last_name])) or "بيك"
    full_name = html.escape(full_name)

    keyboard = InlineKeyboardMarkup()
    keyboard.add(
        InlineKeyboardButton("🚀 بدء الاستخدام", callback_data="start_bot"),
        InlineKeyboardButton("👤 الأدمن", url="https://t.me/w_zqw")
    )

    welcome_text = f"""\
🇩🇿 أهلاً وسهلاً
🇩🇿 {full_name}

🚀 بوت منتعاشرش dz 21

🇩🇿 أرسل يوزر تيك توك
🇩🇿 مع @ أو بدونها
🇩🇿 انتظر 2–3 ثواني
"""
    bot.send_message(message.chat.id, welcome_text, reply_markup=keyboard)

@bot.callback_query_handler(func=lambda call: call.data == "start_bot")
def callback_start_bot(call):
    try:
        safe_answer_callback(call.id, "أرسل الآن يوزر تيك توك (مع @ أو بدونها).")
        bot.send_message(call.message.chat.id, "أرسل الآن اسم المستخدم (مثال: username أو @username)\nسأقوم بجلب معلومات الحساب خلال ثوانٍ.")
    except Exception:
        logger.exception("callback_start_bot failed")

# زر عرض بيانات المصادقة: callback_data = "show_auth:<username>"
@bot.callback_query_handler(func=lambda call: str(call.data).startswith("show_auth:"))
def callback_show_auth(call):
    try:
        # Acknowledge immediately to avoid "query is too old" errors
        safe_answer_callback(call.id, "جاري جلب بيانات المصادقة...")

        # Handle heavy work in a background thread to keep callback short
        def worker():
            try:
                data = call.data.split(":", 1)
                if len(data) != 2:
                    safe_answer_callback(call.id, "بيانات غير صحيحة.")
                    return
                username = data[1].lstrip("@").strip()
                # حاول جلب من الكاش أولاً ثم من oouss إذا لم تتوفر
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


# ------------------ الأداء: تنفيذ متوازي + كاش ------------------
PARALLEL_TIMEOUT = 8
GET_LEVEL_TIMEOUT = 5
MAX_WORKERS = 4

@bot.message_handler(func=lambda m: True)
def handle_username(message):
    username = (message.text or "").strip().lstrip("@")
    if not username:
        bot.reply_to(message, "الرجاء إرسال اسم المستخدم بدون @")
        return

    # قيود بسيطة لطول اليوزر (تجنب إدخالات عشوائية طويلة جداً)
    if len(username) > 64:
        bot.reply_to(message, "اسم المستخدم طويل جداً.")
        return

    status_msg = bot.reply_to(message, f"جارٍ الفحص: @{html.escape(username)} ...")

    # كاش
    tf_res = fetch_cache.get(username)
    oouss_info = info_cache.get(username)
    endpoint_res = endpoint_cache.get(username)
    cached_level = level_cache.get(username)

    # تنفيذ متوازي للنداءات (إن لم تكن في الكاش)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {}
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

        # حاول إيجاد level من tf_res أو الكاش ثم اطلب من oouss.get_level في الخلفية إن لم يوجد
        lvl_from_tf = None
        if isinstance(tf_res, dict):
            lvl_from_tf = tf_res.get("Level_Tikforge") or tf_res.get("Level_Webcast") or tf_res.get("Level") or tf_res.get("level")
        lvl_override = cached_level or None
        if not lvl_from_tf and not lvl_override:
            # محاولة سريعة في الخلفية
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

    merged = merge_results(tf_res if isinstance(tf_res, dict) else {}, oouss_info if isinstance(oouss_info, dict) else {}, endpoint_res if isinstance(endpoint_res, dict) else {}, lvl_override=lvl_override)

    # سجل البحث: اسم الباحث (من message) + اليوزر المطلوب + اسم الحساب (إن وجد)
    try:
        account_name = merged.get("name") or merged.get("username") or ""
        # سجل الحدث في ملف CSV وأرسل إشعارًا للأدمن (إن وُجد)
        log_search_event(message, username, account_name)
    except Exception:
        logger.exception("Failed to log search event")

    # بناء أزرار: إضافة زر لعرض بيانات المصادقة مفصّلة
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔐 كشف طرق المصادقة", callback_data=f"show_auth:{username}"))
    keyboard.add(InlineKeyboardButton("👤 الأدمن", url="https://t.me/w_zqw"))

    # بناء النص وإرساله
    try:
        if hasattr(tf, "build_info_message"):
            text = tf.build_info_message(merged)
            # نضمن عدم تكرار سطر مصدر المستوى
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
            # لو النص طويل جداً نقسمه؛ نلصق الأزرار على الرسالة الأولى فقط
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

    # حذف رسالة "جارٍ الفحص"
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception:
        pass

if __name__ == "__main__":
    logger.info("Bot started")
    bot.infinity_polling(timeout=60, long_polling_timeout=60)