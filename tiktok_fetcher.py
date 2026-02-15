#!/usr/bin/env python3
# tiktok_bot_complete.py
# Module version of "كشف معلومات تيك توك نهائي رمزي21.py"
# This file exposes fetch_and_enrich(username) and build_info_message(enriched).
# NOTE: Sensitive values removed; do NOT include TELEGRAM token or run bot here.

import re
import json
import time
import html
import logging
import datetime
from typing import Optional, Dict, Any, List, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.exceptions import RequestException

# Optional third-party libraries
try:
    from user_agent import generate_user_agent as gen_user_agent
except Exception:
    gen_user_agent = None

try:
    import pycountry
except Exception:
    pycountry = None

# Optional TikForge and SignerPy (best-effort)
TIKFORGE_AVAILABLE = False
try:
    from tikforge import TIKTOK_INFO_V2  # type: ignore
    TIKFORGE_AVAILABLE = True
except Exception:
    TIKFORGE_AVAILABLE = False

SIGNERPY_AVAILABLE = False
try:
    from SignerPy import sign, get  # type: ignore
    SIGNERPY_AVAILABLE = True
except Exception:
    SIGNERPY_AVAILABLE = False

# ------------------ CONFIG (no token here) ------------------
ANALYZER_API_URL = "https://influencers.club/wp-json/tools/v1/proxy/analyzer/"
WEBCAST_URL = "https://webcast22-normal-c-alisg.tiktokv.com/webcast/user/"

# Example headers/params preserved (sensitive cookie values should not be hardcoded in production)
WEBCAST_DEFAULT_HEADERS = {
    "Host": "webcast22-normal-c-alisg.tiktokv.com",
    "cookie": "",  # remove sensitive defaults; if needed, set externally
    "user-agent": gen_user_agent() if gen_user_agent else "com.zhiliaoapp.musically/2023700010 (Linux; Android 11)",
}
WEBCAST_DEFAULT_PARAMS = {
    "ts": str(int(time.time())),
    "iid": "7521814657976928001",
    "device_id": "7405632852996097552",
    # ... rest kept minimal; code will override as needed
}

# ------------------ HTTP session ------------------
HTTP_TIMEOUT = 10
session = requests.Session()
retries = Retry(total=3, backoff_factor=0.8, status_forcelist=(429, 500, 502, 503, 504))
session.mount("https://", HTTPAdapter(max_retries=retries))
session.mount("http://", HTTPAdapter(max_retries=retries))
session.headers.update({"User-Agent": gen_user_agent() if gen_user_agent else "Mozilla/5.0 (compatible; Bot/1.0)"})

# ------------------ logging ------------------
logger = logging.getLogger("tiktok_bot_complete")
logger.addHandler(logging.NullHandler())

MAX_TELEGRAM_MSG = 4000
MAX_PHOTO_CAPTION = 1024

# ------------------ utilities ------------------
def clean_text_for_message(text: Any, max_len: int = 1000) -> str:
    if text is None:
        return ""
    try:
        s = str(text)
        s = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)
        s = re.sub(r'\s+', ' ', s).strip()
        if len(s) > max_len:
            s = s[: max_len - 3] + "..."
        return s
    except Exception:
        return str(text)

def escape_html(s: str) -> str:
    return html.escape(s or "")

def format_number(num: Any) -> str:
    if num is None or num == "":
        return ""
    try:
        if isinstance(num, str):
            num = str(num).replace(',', '')
            num = float(num) if '.' in num else int(num)
        n = float(num)
        if n >= 1_000_000_000:
            return f"{n/1_000_000_000:.1f}B"
        if n >= 1_000_000:
            return f"{n/1_000_000:.1f}M"
        if n >= 1000:
            return f"{n/1000:.1f}K"
        return str(int(n)) if n.is_integer() else str(n)
    except Exception:
        return str(num)

def country_name_and_flag(region_value: str) -> Tuple[str, str]:
    if not region_value:
        return ("", "")
    rv = str(region_value).strip()
    flag = ""
    name = ""
    if len(rv) == 2:
        try:
            if pycountry:
                c = pycountry.countries.get(alpha_2=rv.upper())
                if c:
                    name = getattr(c, "name", "") or ""
            offset = 127397
            flag = chr(ord(rv[0].upper()) + offset) + chr(ord(rv[1].upper()) + offset)
            return (name or rv, flag)
        except Exception:
            pass
    if pycountry:
        try:
            c = pycountry.countries.get(name=rv)
            if not c:
                for country in pycountry.countries:
                    if rv.lower() in getattr(country, "name", "").lower() or rv.lower() in getattr(country, "official_name", "").lower():
                        c = country
                        break
            if c:
                name = getattr(c, "name", "")
                alpha2 = getattr(c, "alpha_2", "")
                if alpha2:
                    try:
                        offset = 127397
                        flag = chr(ord(alpha2[0].upper()) + offset) + chr(ord(alpha2[1].upper()) + offset)
                    except Exception:
                        flag = ""
                return (name, flag)
        except Exception:
            pass
    return (rv, "")

# ------------------ robust JSON extraction ------------------
def _extract_json_from_pos(text: str, start_pos: int) -> Optional[Dict[str, Any]]:
    try:
        i = start_pos
        n = len(text)
        while i < n and text[i] != '{':
            i += 1
        if i >= n:
            return None
        start = i
        stack = []
        in_str = False
        escape = False
        for j in range(i, n):
            ch = text[j]
            if ch == '"' and not escape:
                in_str = not in_str
            if ch == '\\' and not escape:
                escape = True
            else:
                escape = False
            if not in_str:
                if ch == '{':
                    stack.append('{')
                elif ch == '}':
                    if stack:
                        stack.pop()
                        if not stack:
                            raw = text[start:j+1]
                            try:
                                return json.loads(raw)
                            except Exception:
                                try:
                                    unescaped = html.unescape(raw)
                                    return json.loads(unescaped)
                                except Exception:
                                    return None
        return None
    except Exception:
        logger.exception("_extract_json_from_pos failed")
        return None

def find_json_in_html(html_text: str) -> Optional[Dict[str, Any]]:
    try:
        if "webapp.user-detail" in html_text:
            idx = html_text.find("webapp.user-detail")
            back = html_text.rfind("{", 0, idx)
            if back != -1:
                found = _extract_json_from_pos(html_text, back)
                if isinstance(found, dict) and "__DEFAULT_SCOPE__" in found:
                    return found

        patterns = [
            r'({"__DEFAULT_SCOPE__":)',
            r'window\.__INIT_PROPS__\s*=\s*',
            r'window\.__SIGI_STATE__\s*=\s*',
            r'window\.__PRELOADED_STATE__\s*=\s*',
            r'<script id="SIGI_STATE"',
            r'<script id="__NEXT_DATA__"',
            r'<script type="application/ld\+json">'
        ]
        for pat in patterns:
            m = re.search(pat, html_text, flags=re.DOTALL)
            if m:
                start = m.start()
                brace_pos = html_text.find("{", start)
                if brace_pos != -1:
                    extracted = _extract_json_from_pos(html_text, brace_pos)
                    if extracted:
                        return extracted

        for m in re.finditer(r'<script[^>]*>([\s\S]{200,100000})</script>', html_text, flags=re.IGNORECASE):
            content = m.group(1)
            for key in ('{"__DEFAULT_SCOPE__"', 'window.__SIGI_STATE__', '"webapp.user-detail"', '"UserModule"'):
                pos = content.find(key)
                if pos != -1:
                    abs_pos = m.start(1) + pos
                    extracted = _extract_json_from_pos(html_text, abs_pos)
                    if extracted:
                        return extracted
        return None
    except Exception:
        logger.exception("find_json_in_html (improved) failed")
        return None

# ------------------ fetch with fallbacks ------------------
def fetch_with_fallbacks(username: str, timeout: int = HTTP_TIMEOUT) -> Tuple[Optional[str], str]:
    urls = [
        f"https://www.tiktok.com/@{username}",
        f"https://www.tiktok.com/@{username}?lang=en",
        f"https://m.tiktok.com/@{username}",
        f"https://www.tiktok.com/@{username}/?lang=en",
    ]
    user_agents = [
        session.headers.get("User-Agent") or "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Mozilla/5.0 (Linux; Android 11; Mobile) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116 Mobile Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 15_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.6 Mobile/15E148 Safari/604.1",
    ]
    debug_parts = []
    for url in urls:
        for ua in user_agents:
            try:
                headers = {"User-Agent": ua, "Accept-Language": "en-US,en;q=0.9"}
                r = session.get(url, headers=headers, timeout=timeout, allow_redirects=True)
                debug_parts.append(f"{url} -> {r.status_code}, len={len(r.text or '')}")
                if r.status_code == 200 and r.text and len(r.text) > 500:
                    return (r.text, "OK: " + debug_parts[-1])
            except Exception as e:
                debug_parts.append(f"{url} -> EXC {e}")
                continue
    return (None, "FAILED: " + " | ".join(debug_parts[:8]))

# ------------------ parse user info from JSON ------------------
def locate_userinfo(json_blob: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        if "__DEFAULT_SCOPE__" in json_blob:
            scope = json_blob["__DEFAULT_SCOPE__"]
            ud = scope.get("webapp.user-detail", {})
            if ud and "userInfo" in ud:
                return ud["userInfo"]
        for k in ("user", "UserModule", "ProfileModule", "ItemModule"):
            if k in json_blob:
                possible = json_blob.get(k)
                if isinstance(possible, dict):
                    if "users" in possible:
                        users = possible.get("users", {})
                        if users:
                            first = next(iter(users.values()))
                            return first
                    if "userInfo" in possible:
                        return possible.get("userInfo")
        def find_recursive(obj):
            if isinstance(obj, dict):
                if "userInfo" in obj:
                    return obj["userInfo"]
                if "user" in obj and isinstance(obj["user"], dict):
                    return obj["user"]
                for v in obj.values():
                    res = find_recursive(v)
                    if res:
                        return res
            elif isinstance(obj, list):
                for item in obj:
                    res = find_recursive(item)
                    if res:
                        return res
            return None
        return find_recursive(json_blob)
    except Exception:
        logger.exception("Error locating userinfo in JSON")
        return None

def extract_fields_from_page(userinfo: Dict[str, Any], json_blob: Dict[str, Any], html_text: str) -> Dict[str, Any]:
    try:
        user = userinfo.get("user") if isinstance(userinfo, dict) and "user" in userinfo else userinfo
        stats = userinfo.get("stats", {}) if isinstance(userinfo, dict) else {}
        stats_v2 = userinfo.get("statsV2", {}) if isinstance(userinfo, dict) else {}
        user_id = user.get('id', '') if isinstance(user, dict) else ''
        name = user.get('nickname', '') if isinstance(user, dict) else ''
        unique_id = user.get('uniqueId', '') if isinstance(user, dict) else ''
        bio = user.get('signature', '') if isinstance(user, dict) else ''
        country = user.get('region', '') if isinstance(user, dict) else ''
        verified = user.get('verified', False) if isinstance(user, dict) else False
        private = user.get('privateAccount', False) if isinstance(user, dict) else False
        secid = user.get('secUid', '') if isinstance(user, dict) else ''
        create_time = user.get('createTime', '') if isinstance(user, dict) else ''
        avatar_larger = user.get('avatarLarger', '') if isinstance(user, dict) else ''
        bio_link_url = (user.get('bioLink') or {}).get('link', '') if isinstance(user, dict) else ''
        commerce_user = user.get('commerceUserInfo', {}).get('commerceUser', False) if isinstance(user, dict) else False
        is_organization = user.get('isOrganization', 0) if isinstance(user, dict) else 0
        language = user.get('language', '') if isinstance(user, dict) else ''
        comment_setting = user.get('commentSetting', 0) if isinstance(user, dict) else 0
        duet_setting = user.get('duetSetting', 0) if isinstance(user, dict) else 0
        stitch_setting = user.get('stitchSetting', 0) if isinstance(user, dict) else 0
        download_setting = user.get('downloadSetting', 0) if isinstance(user, dict) else 0

        followers = stats_v2.get('followerCount', stats.get('followerCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''
        following = stats_v2.get('followingCount', stats.get('followingCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''
        likes = stats_v2.get('heartCount', stats.get('heartCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''
        videos = stats_v2.get('videoCount', stats.get('videoCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''
        digg_count = stats_v2.get('diggCount', stats.get('diggCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''
        friend_count = stats_v2.get('friendCount', stats.get('friendCount', '')) if isinstance(stats_v2, dict) or isinstance(stats, dict) else ''

        created_date = ""
        if create_time:
            try:
                created_date = datetime.datetime.fromtimestamp(int(create_time)).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                created_date = ""

        country_name = ""
        country_flag = ""
        if country:
            try:
                if pycountry:
                    if len(str(country)) == 2:
                        cobj = pycountry.countries.get(alpha_2=country.upper())
                        if cobj:
                            country_name = getattr(cobj, "name", "")
                            alpha2 = getattr(cobj, "alpha_2", "")
                            if alpha2:
                                offset = 127397
                                country_flag = chr(ord(alpha2[0].upper()) + offset) + chr(ord(alpha2[1].upper()) + offset)
                    else:
                        country_name = country
            except Exception:
                country_name = country

        cleaned_name = clean_text_for_message(name)

        web_info = {
            "user_id": user_id,
            "name": cleaned_name,
            "username": unique_id,
            "bio": clean_text_for_message(bio),
            "country": country,
            "country_name": country_name,
            "country_flag": country_flag,
            "verified": verified,
            "private": private,
            "commerce_user": commerce_user,
            "is_organization": is_organization,
            "language": language,
            "followers": followers,
            "following": following,
            "likes": likes,
            "videos": videos,
            "digg_count": digg_count,
            "friend_count": friend_count,
            "secid": secid,
            "created_date": created_date,
            "avatar_larger": avatar_larger,
            "bio_link": bio_link_url,
            "comment_setting": comment_setting,
            "duet_setting": duet_setting,
            "stitch_setting": stitch_setting,
            "download_setting": download_setting
        }
        return web_info
    except Exception:
        logger.exception("extract_fields_from_page failed")
        return {}

# (TikForge/SignerPy/enrich/get_level_via_webcast/call_analyzer kept as in original file)
# For brevity in this snippet, assume the rest of helper functions (load_tikforge_device,
# enrich_with_tikforge, get_level_via_webcast, call_analyzer) are present here as in your source.
# ... (you can paste the rest of the code you sent if you want the full module)

# Main fetch_and_enrich (keeps behavior as your provided file)
def fetch_and_enrich(username: str) -> Dict[str, Any]:
    username = username.lstrip("@")
    try:
        html_text, dbg = fetch_with_fallbacks(username)
        if not html_text:
            logger.warning("fetch_and_enrich fetch failed: %s", dbg)
            return {"ok": False, "error": "Could not fetch TikTok page (maybe blocked). Debug: " + dbg, "username": username}

        json_blob = find_json_in_html(html_text)
        if not json_blob:
            logger.warning("find_json_in_html failed, debug: %s", dbg)
            try:
                with open(f"debug_{username[:10]}.html", "w", encoding="utf-8") as f:
                    f.write(html_text[:20000])
            except Exception:
                pass
            return {"ok": False, "error": "Could not find embedded JSON on TikTok page", "username": username}

        userinfo = locate_userinfo(json_blob)
        if not userinfo:
            keys_preview = list(json_blob.keys())[:6] if isinstance(json_blob, dict) else []
            return {"ok": False, "error": "Could not locate user info in JSON", "username": username, "json_preview": keys_preview}

        page_data = extract_fields_from_page(userinfo, json_blob, html_text)
        merged = dict(page_data)

        # country handling + enrichers
        if (not merged.get("country") or merged.get("country") in ("", "N/A")):
            try:
                tikf_dev = load_tikforge_device()
                if tikf_dev.get("region"):
                    merged["country"] = tikf_dev["region"]
            except Exception:
                pass

        if merged.get("country") and not merged.get("country_name"):
            cn, cf = country_name_and_flag(merged["country"])
            merged["country_name"] = cn
            merged["country_flag"] = cf

        try:
            merged = enrich_with_tikforge(username, merged)
        except Exception:
            pass

        if not merged.get("Level_Tikforge"):
            try:
                if SIGNERPY_AVAILABLE:
                    lvl = get_level_via_webcast(merged.get("user_id", ""))
                    if lvl:
                        merged["Level_Webcast"] = lvl
            except Exception:
                pass

        try:
            analytics = call_analyzer(username)
            if analytics:
                merged["analytics"] = analytics
        except Exception:
            pass

        merged["ok"] = True
        merged["username"] = username
        return merged

    except RequestException as e:
        return {"ok": False, "error": f"Network error: {e}", "username": username}
    except Exception as e:
        logger.exception("Unexpected error in fetch_and_enrich")
        return {"ok": False, "error": f"Unexpected: {e}", "username": username}

def build_info_message(enriched: Dict[str, Any]) -> str:
    username = enriched.get("username", "")
    web_info = enriched
    analytics = enriched.get("analytics", {})

    info_text = "🔍 <b>معلومات حساب تيك توك</b>\n\n"
    info_text += f"👤 <b>اليوزر:</b> @{escape_html(username)}\n"
    info_text += f"📛 <b>الاسم:</b> {escape_html(web_info.get('name',''))}\n"

    if web_info.get('bio'):
        info_text += f"📝 <b>البايو:</b> {escape_html(web_info.get('bio',''))}\n"
    if web_info.get('bio_link'):
        info_text += f"🔗 <b>الرابط:</b> {escape_html(web_info.get('bio_link',''))}\n"

    # الإحصاءات
    info_text += "\n📊 <b>الإحصائيات:</b>\n"
    info_text += f"👥 <b>المتابعين:</b> {escape_html(format_number(web_info.get('followers','')))}\n"
    info_text += f"🔄 <b>يتبع:</b> {escape_html(format_number(web_info.get('following','')))}\n"
    info_text += f"❤️ <b>مجموع لايكات:</b> {escape_html(format_number(web_info.get('likes','')))}\n"
    info_text += f"🎬 <b>عدد الفيديوات:</b> {escape_html(format_number(web_info.get('videos','')))}\n"
    if web_info.get('digg_count'):
        info_text += f"👍 <b>الفيديوات المعجبة:</b> {escape_html(format_number(web_info.get('digg_count','')))}\n"
    if web_info.get('friend_count'):
        info_text += f"🤝 <b>عدد الأصدقاء:</b> {escape_html(format_number(web_info.get('friend_count','')))}\n"

    # معلومات الحساب
    info_text += "\n🔐 <b>معلومات الحساب:</b>\n"
    info_text += f"✅ <b>مؤكد:</b> {'اي' if web_info.get('verified') else 'لا'}\n"
    info_text += f"🔒 <b>الحالة:</b> {'خاص' if web_info.get('private') else 'عام'}\n"
    info_text += f"💼 <b>نوع الحساب:</b> {'تجاري' if web_info.get('commerce_user') else 'شخصي'}\n"
    info_text += f"🏢 <b>منظمة:</b> {'اي' if web_info.get('is_organization') == 1 else 'لا'}\n"

    # البلد
    country = web_info.get('country') or ""
    country_name = web_info.get('country_name') or ""
    country_flag = web_info.get('country_flag') or ""
    if country:
        if not country_name or not country_flag:
            cn, cf = country_name_and_flag(country)
            country_name = cn
            country_flag = cf
        info_text += f"🌍 <b>البلد:</b> {escape_html(country_name)} {country_flag}\n"

    if web_info.get('language'):
        info_text += f"🗣️ <b>اللغة:</b> {escape_html(web_info.get('language',''))}\n"
    if web_info.get('created_date'):
        info_text += f"📅 <b>تاريخ التسجيل:</b> {escape_html(web_info.get('created_date',''))}\n"

    level = web_info.get('Level_Tikforge') or web_info.get('Level_Webcast') or analytics.get('level') or web_info.get('level')
    if level:
        info_text += f"⭐ <b>مستوى الحساب:</b> {escape_html(str(level))}\n"

    def get_settings_desc(v): return {0:"الكل",1:"الاصدقاء",2:"ماكو"}.get(int(v), "مو معروف")
    info_text += "\n⚙️ <b>الإعدادات:</b>\n"
    info_text += f"💬 <b>التعليقات:</b> {escape_html(get_settings_desc(web_info.get('comment_setting',0)))}\n"
    info_text += f"🎵 <b>دويت:</b> {escape_html(get_settings_desc(web_info.get('duet_setting',0)))}\n"
    info_text += f"✂️ <b>ستيتش:</b> {escape_html(get_settings_desc(web_info.get('stitch_setting',0)))}\n"
    info_text += f"📥 <b>التنزيل:</b> {escape_html(get_settings_desc(web_info.get('download_setting',0)))}\n"

    if analytics:
        info_text += "\n📈 <b>تحليل:</b>\n"
        if analytics.get('avg_likes') is not None:
            info_text += f"📊 <b>متوسط الإعجابات:</b> {escape_html(format_number(analytics.get('avg_likes')))}\n"
        if analytics.get('engagement_rate') is not None:
            try:
                er = float(analytics.get('engagement_rate',0)); info_text += f"📈 <b>نسبة التفاعل:</b> {er:.2f}%\n"
            except: pass
        if analytics.get('avg_views') is not None:
            info_text += f"👀 <b>متوسط المشاهدات:</b> {escape_html(format_number(analytics.get('avg_views')))}\n"

    info_text += "\n🔧 <b>معلومات تقنية:</b>\n"
    info_text += f"🆔 <b>آيدي اليوزر:</b> {escape_html(str(web_info.get('user_id','')))}\n"
    info_text += f"🔐 <b>SecUID:</b> {escape_html(web_info.get('secid',''))}\n"

    info_text += "\n🔧 <i>by DEV👉 Ramzi 21</i>"
    return info_text

def split_message_for_telegram(text: str, max_len: int = MAX_TELEGRAM_MSG) -> List[str]:
    if len(text) <= max_len:
        return [text]
    parts = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            parts.append(remaining)
            break
        split_index = remaining.rfind('\n', 0, max_len)
        if split_index == -1:
            split_index = max_len
        parts.append(remaining[:split_index])
        remaining = remaining[split_index:].lstrip()
    return parts