"""
merge_logic.py

دمج نتائج المصدرين (page_json from tiktok_fetcher, ouss from ouss) بدون تكرار.
يُعيد بنية تحتوي على الحقل "data" مع القيم النهائية، "sources" و "alternatives".
"""
from typing import Dict, Any


def merge_results(page_json: Dict[str, Any], ouss: Dict[str, Any]) -> Dict[str, Any]:
    """
    page_json: ناتج fetch من tiktok_fetcher.fetch_and_enrich (قد يكون dict كبير يحتوي على حقول مباشرة)
    ouss: ناتج من ouss.info + available_ways (جمعهما في dict واحد)
    تعيد dict مدموج مع الحقل 'sources' و 'alternatives' و 'data' النهائي.
    """
    merged = {
        "data": {},
        "sources": [],
        "alternatives": {}
    }

    # Helper
    def set_field(key, value, source):
        if value is None or value == "":
            return
        if key not in merged["data"] or merged["data"].get(key) in (None, ""):
            merged["data"][key] = value
            merged["data"].setdefault("_meta", {}).setdefault(key, {})["source"] = source
        else:
            # if value identical -> ignore
            if str(merged["data"][key]) == str(value):
                # already present, but ensure source list includes it (handled by sources list)
                pass
            else:
                # keep existing as primary, but record alternative
                merged["alternatives"].setdefault(key, []).append({"source": source, "value": value})

    # Record sources
    if page_json:
        merged["sources"].append("page_json")
    if ouss:
        merged["sources"].append("ouss")

    # TECHNICAL: prefer page_json for ids & secid & created_date
    for k in ("user_id", "secid", "created_date", "cdt", "username_modifytime"):
        v = page_json.get(k)
        if v:
            set_field(k, v, "page_json")
        else:
            v2 = ouss.get(k)
            if v2:
                set_field(k, v2, "ouss")

    # NAME/BIO: choose longer non-empty (page_json preferred if equal)
    for k in ("name", "bio", "username"):
        a = page_json.get(k) or ""
        b = ouss.get(k) or ""
        if a and b:
            pick = a if len(str(a)) >= len(str(b)) else b
            source = "page_json" if pick == a else "ouss"
            set_field(k, pick, source)
            # keep the other as alternative
            other = b if pick == a else a
            merged["alternatives"].setdefault(k, []).append(
                {"source": ("ouss" if pick == "page_json" else "page_json"), "value": other}
            )
        elif a:
            set_field(k, a, "page_json")
        elif b:
            set_field(k, b, "ouss")

    # AVATAR: prefer page_json then ouss
    avatar_candidates = []
    for k in ("avatar_larger", "avatar", "avatar_l"):
        if page_json.get(k):
            avatar_candidates.append((page_json.get(k), "page_json"))
    if ouss.get("avatar"):
        avatar_candidates.append((ouss.get("avatar"), "ouss"))
    if avatar_candidates:
        set_field("avatar", avatar_candidates[0][0], avatar_candidates[0][1])
        for v, s in avatar_candidates[1:]:
            merged["alternatives"].setdefault("avatar", []).append({"source": s, "value": v})

    # COUNTRY: try normalized name/flag from page_json then ouss
    for k in ("country_name", "country", "countryn", "countryf"):
        v = page_json.get(k)
        if v:
            set_field(k, v, "page_json")
    # then ouss for missing
    for k in ("country", "countryn", "countryf"):
        if merged["data"].get(k) is None and ouss.get(k):
            set_field(k, ouss.get(k), "ouss")

    # STATS: followers/following/likes/videos/digg_count/friend_count
    stats_keys = ["followers", "following", "likes", "video", "videos", "digg_count", "friend_count", "like"]
    # Normalize aliases: prefer canonical keys in merged.data (followers, following, likes, videos)
    alias_map = {
        "video": "videos",
        "like": "likes"
    }
    for key in stats_keys:
        p = page_json.get(key)
        o = ouss.get(key)
        target_key = alias_map.get(key, key)
        if p is not None and p != "":
            set_field(target_key, p, "page_json")
            if o not in (None, "", p):
                merged["alternatives"].setdefault(target_key, []).append({"source": "ouss", "value": o})
        elif o not in (None, ""):
            set_field(target_key, o, "ouss")

    # SECURITY: use ouss.available_ways/security if present
    sec = {}
    # o u ss module may place result as returned by find_account_end_point: {'data': {...}, ...}
    if isinstance(ouss.get("security"), dict) and ouss.get("security"):
        sec = ouss.get("security")
    else:
        # try ouss['data'] pattern
        if isinstance(ouss.get("data"), dict) and ouss.get("data"):
            sec = ouss.get("data")
    if sec:
        merged["data"].setdefault("security", {}).update(sec)
        merged["data"]["security"]["source"] = "ouss"

    # LEVEL: if both exist, keep both tagged; else keep whichever
    level_p = page_json.get("level") or page_json.get("Level_Tikforge") or page_json.get("Level_Webcast")
    level_o = ouss.get("level") or ouss.get("Level_Tikforge") or ouss.get("Level_Webcast")
    if level_p and level_o and level_p != level_o:
        merged["data"]["level"] = {"page_json": level_p, "ouss": level_o}
    elif level_p:
        set_field("level", level_p, "page_json")
    elif level_o:
        set_field("level", level_o, "ouss")

    # SETTINGS (comments/duet/stitch/download) -> prefer page_json
    settings_keys = ["comment_setting", "duet_setting", "stitch_setting", "download_setting"]
    for k in settings_keys:
        v = page_json.get(k)
        if v is not None and v != "":
            set_field(k, v, "page_json")
        else:
            vv = ouss.get(k)
            if vv is not None and vv != "":
                set_field(k, vv, "ouss")

    # language
    if page_json.get("language"):
        set_field("language", page_json.get("language"), "page_json")
    elif ouss.get("language"):
        set_field("language", ouss.get("language"), "ouss")

    # final normalization (numbers -> int where possible)
    for k in ["followers", "following", "likes", "videos", "digg_count", "friend_count"]:
        if merged["data"].get(k) is not None:
            try:
                merged["data"][k] = int(str(merged["data"][k]).replace(',', '').replace('.', ''))
            except Exception:
                # leave original if can't parse
                pass

    return merged