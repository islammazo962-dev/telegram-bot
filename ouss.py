# oouss.py - dynamic hosts loading + optional hosts generator integrated
import requests
import secrets
import random
import uuid
import time
import os
import binascii
import re
from urllib.parse import urlencode
import SignerPy
from MedoSigner import Argus, Gorgon, md5, Ladon
import string
import telebot
from datetime import datetime, timedelta
import pycountry
import codecs
import logging
import threading
from typing import List, Set, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import socket
import argparse

# Optional: configure basic logging for this module
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ouss")

# ---------------- Config: dynamic hosts loading ----------------
# Local hosts file (one host per line). Can contain comments starting with '#'.
HOSTS_FILE = os.getenv("HOSTS_FILE", "hosts.txt")

# Optional comma-separated URLs (ENV) to fetch additional host lists (plain text, one host per line)
_HOSTS_URLS_ENV = os.getenv("HOSTS_URLS", "")
HOSTS_URLS = [u.strip() for u in _HOSTS_URLS_ENV.split(",") if u.strip()]

# Maximum hosts to load (safety cap)
MAX_LOADED_HOSTS = int(os.getenv("MAX_LOADED_HOSTS", "10000"))

# Timeout for fetching remote host lists
HOSTS_FETCH_TIMEOUT = int(os.getenv("HOSTS_FETCH_TIMEOUT", "8"))

# ---------------- Seed Hostnames (DEFAULT list) ----------------
DEFAULT_BASE_HOSTS = [
    # original base hosts (seed/fallback)
    "api16-normal-c-alisg.tiktokv.com", "api.tiktokv.com", "api-h2.tiktokv.com",
    "api-va.tiktokv.com", "api16.tiktokv.com", "api16-va.tiktokv.com",
    "api19.tiktokv.com", "api19-va.tiktokv.com", "api21.tiktokv.com",
    "api15-h2.tiktokv.com", "api21-h2.tiktokv.com", "api21-va.tiktokv.com",
    "api22.tiktokv.com", "api22-va.tiktokv.com", "api-t.tiktok.com",
    "api16-normal-baseline.tiktokv.com", "api23-normal-zr.tiktokv.com",
    "api21-normal.tiktokv.com", "api22-normal-zr.tiktokv.com", "api33-normal.tiktokv.com",
    "api22-normal.tiktokv.com", "api31-normal.tiktokv.com", "api15-normal.tiktokv.com",
    "api31-normal-cost-sg.tiktokv.com", "api3-normal.tiktokv.com", "api31-normal-zr.tiktokv.com",
    "api9-normal.tiktokv.com", "api16-normal.tiktokv.com", "api16-normal.ttapis.com",
    "api19-normal-zr.tiktokv.com", "api16-normal-zr.tiktokv.com", "api16-normal-apix.tiktokv.com",
    "api74-normal.tiktokv.com", "api32-normal-zr.tiktokv.com", "api23-normal-tiktokv.com",
    "api32-normal.tiktokv.com", "api16-normal-quic.tiktokv.com", "api-normal.tiktokv.com",
    "api16-normal-apix-quic.tiktokv.com", "api19-normal-tiktokv.com", "api19-normal.tiktokv.com",
    "api31-normal-cost-mys.tiktokv.com", "im-va.tiktokv.com", "imapi-16.tiktokv.com",
    "imapi-16.musical.ly", "imapi-mu.isnssdk.com", "api.tiktok.com", "api.ttapis.com",
    "api.tiktokv.us", "api.tiktokv.eu", "api.tiktokw.us", "api.tiktokw.eu",
    "webcast-ws16-normal-useast5.tiktokv.us", "webcast-ws16-normal-useast8.tiktokv.us",
    "webcast16-normal-useast5.tiktokv.us", "webcast16-normal-useast8.tiktokv.us",
    "webcast19-normal-useast5.tiktokv.us", "webcast19-normal-useast8.tiktokv.us",
    "api16-core-useast5.tiktokv.us", "api16-core-useast8.tiktokv.us",
    "api16-normal-useast5.tiktokv.us", "api16-normal-useast8.tiktokv.us",
    "api19-core-useast5.tiktokv.us", "api19-core-useast8.tiktokv.us",
    "api19-normal-useast5.tiktokv.us", "api19-normal-useast8.tiktokv.us",
    "ad.tiktokv.us", "tiktokv.us", "tiktokw.us",
    # EU hosts (merged)
    "api16-normal-eu-ams.tiktokv.com",
    "api16-normal-eu-fra.tiktokv.com",
    "api16-normal-eu-lon.tiktokv.com",
    "api16-normal-eu-par.tiktokv.com",
    "api16-normal-eu-mad.tiktokv.com",
    "api16-normal-eu-zrh.tiktokv.com",
    "api16-normal-eu-arn.tiktokv.com",
    "api16-normal-eu-waw.tiktokv.com",
    "api16-normal-eu-mil.tiktokv.com",
    "webcast16-normal-eu.tiktokv.com",
    "api16-core-eu.tiktokv.com",
    "api16-normal-eu-quic.tiktokv.com",
    "api-eu.tiktokv.com",
    "api16-normal-eu-ams.snssdk.com",
    # additional common EU webcast/core endpoints (examples that may be useful)
    "webcast16-normal-no1a.tiktokv.eu",
    "webcast16-normal-no1.tiktokv.eu",
    "api16-core-eu-ams.tiktokv.com",
    "api16-core-eu-fra.tiktokv.com",
]

# ---------------- Patterns + generator config ----------------
PATTERNS = [
    "api{n}.tiktokv.com",
    "api{n}-normal.tiktokv.com",
    "api{n}-normal-zr.tiktokv.com",
    "api{n}-normal-apix.tiktokv.com",
    "api{n}-normal-quic.tiktokv.com",
    "api{n}-core.tiktokv.com",
    "api{n}-core-eu.tiktokv.com",
    "api{n}-normal-eu-{region}.tiktokv.com",
    "webcast{n}-normal.tiktokv.com",
    "imapi-{n}.tiktokv.com",
    "api{n}-normal.ttapis.com",
    "api{n}.tiktok.com",
]
EU_REGIONS = ["ams", "fra", "lon", "par", "mad", "zrh", "arn", "waw", "mil", "ber"]

# ---------------- Internal cache + lock for loaded hosts ----------------
_loaded_hosts_lock = threading.Lock()
_loaded_hosts_cache: Optional[List[str]] = None


def _dedupe_preserve_order(seq: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _read_hosts_file(path: str) -> List[str]:
    hosts: List[str] = []
    if not os.path.exists(path):
        return hosts
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                hosts.append(s)
    except Exception:
        logger.exception("Failed to read hosts file %s", path)
    return hosts


def _fetch_hosts_from_url(url: str) -> List[str]:
    try:
        r = requests.get(url, timeout=HOSTS_FETCH_TIMEOUT)
        if r.status_code == 200 and r.text:
            lines = []
            for line in r.text.splitlines():
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                lines.append(s)
            return lines
        else:
            logger.debug("hosts URL %s returned status %s", url, r.status_code)
    except Exception:
        logger.debug("Failed to fetch hosts from %s", url, exc_info=True)
    return []


def load_base_hosts(force_reload: bool = False) -> List[str]:
    """
    Load and return a deduplicated list of hosts.
    - Reads HOSTS_FILE (if present)
    - Optionally fetches HOSTS_URLS
    - Merges with DEFAULT_BASE_HOSTS
    - Respects MAX_LOADED_HOSTS
    Caches the result in memory; use force_reload=True to reload.
    """
    global _loaded_hosts_cache
    with _loaded_hosts_lock:
        if _loaded_hosts_cache is not None and not force_reload:
            return _loaded_hosts_cache

        seen: Set[str] = set()
        result: List[str] = []

        # Start with DEFAULT_BASE_HOSTS (seed)
        for h in DEFAULT_BASE_HOSTS:
            if h and h not in seen:
                seen.add(h)
                result.append(h)
            if len(result) >= MAX_LOADED_HOSTS:
                _loaded_hosts_cache = result[:MAX_LOADED_HOSTS]
                logger.info("Loaded %d hosts (capped by MAX_LOADED_HOSTS)", len(_loaded_hosts_cache))
                return _loaded_hosts_cache

        # Load local file
        local = _read_hosts_file(HOSTS_FILE)
        for entry in local:
            # If entry looks like a URL, extract hostname
            if entry.startswith("http://") or entry.startswith("https://"):
                try:
                    parsed = requests.utils.urlparse(entry)
                    host = parsed.netloc.split(':')[0]
                except Exception:
                    host = entry
            else:
                host = entry.split('/')[0].split(':')[0]
            if host and host not in seen:
                seen.add(host)
                result.append(host)
            if len(result) >= MAX_LOADED_HOSTS:
                break

        # Fetch remote lists
        if len(result) < MAX_LOADED_HOSTS and HOSTS_URLS:
            for url in HOSTS_URLS:
                fetched = _fetch_hosts_from_url(url)
                for entry in fetched:
                    host = entry.split('/')[0].split(':')[0]
                    if host and host not in seen:
                        seen.add(host)
                        result.append(host)
                    if len(result) >= MAX_LOADED_HOSTS:
                        break
                if len(result) >= MAX_LOADED_HOSTS:
                    break

        # Final trim
        if len(result) > MAX_LOADED_HOSTS:
            result = result[:MAX_LOADED_HOSTS]

        _loaded_hosts_cache = _dedupe_preserve_order(result)
        logger.info("Loaded %d hosts (MAX=%s).", len(_loaded_hosts_cache), MAX_LOADED_HOSTS)
        return _loaded_hosts_cache


def reload_hostnames() -> List[str]:
    """Force reload the hostnames from disk/remote and return the new list."""
    return load_base_hosts(force_reload=True)


# ---------------- Hostnames: load once at import time (can be reloaded via reload_hostnames) ----------------
Hostnames = load_base_hosts()
logger.info("Hostnames built: %d hosts", len(Hostnames))
# -------------------------------------------------------------------------


# ---------------- Host probing / helper for generator (optional resolve) ----------------
def resolve_host(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
        return True
    except Exception:
        return False


def resolve_hosts_concurrent(hosts: List[str], concurrency: int = 40) -> List[str]:
    resolvable = []
    lock = threading.Lock()

    def worker(h):
        ok = resolve_host(h)
        if ok:
            with lock:
                resolvable.append(h)
        return h, ok

    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = [ex.submit(worker, h) for h in hosts]
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception:
                pass
    return resolvable


# ---------------- Patterns expansion + generator ----------------
def expand_patterns(start: int, end: int, include_regions: bool = True) -> List[str]:
    """Generate hostnames from PATTERNS using numbers in [start,end]."""
    out: List[str] = []
    for n in range(start, end + 1):
        for p in PATTERNS:
            if "{region}" in p and include_regions:
                for r in EU_REGIONS:
                    out.append(p.format(n=n, region=r))
            else:
                out.append(p.format(n=n))
    return out


def generate_hosts(start: int = 0, end: int = 199, extra_hosts: Optional[List[str]] = None, max_count: int = 5000, resolve: bool = False, concurrency: int = 40) -> List[str]:
    """
    Generate hosts by combining extra_hosts + expanded patterns.
    - Dedupe while preserving order.
    - Optionally resolve DNS to keep only resolvable hosts.
    - Truncate to max_count.
    """
    if extra_hosts is None:
        extra_hosts = DEFAULT_BASE_HOSTS.copy()

    candidates: List[str] = list(extra_hosts)
    # expand patterns
    candidates += expand_patterns(start, end, include_regions=True)

    # dedupe preserving order
    seen: Set[str] = set()
    deduped: List[str] = []
    for h in candidates:
        if h not in seen:
            seen.add(h)
            deduped.append(h)
        if len(deduped) >= max_count:
            break

    final: List[str]
    if resolve:
        logger.info("Resolving %d hosts (concurrency=%d)...", len(deduped), concurrency)
        resolvable = resolve_hosts_concurrent(deduped, concurrency=concurrency)
        resolv_set = set(resolvable)
        final = [h for h in deduped if h in resolv_set]
    else:
        final = deduped

    if len(final) > max_count:
        final = final[:max_count]
    return final


def write_hosts_file(hosts: List[str], path: str):
    try:
        with open(path, "w", encoding="utf-8") as f:
            for h in hosts:
                f.write(h.strip() + "\n")
        logger.info("Wrote %d hosts to %s", len(hosts), path)
    except Exception:
        logger.exception("Failed to write hosts file %s", path)


# ---------------- Original API functions (unchanged) ----------------
def get_available_ways(host, token, params, cookies, proxies=None):
    try:
        params_step2 = params.copy()
        params_step2['not_login_ticket'] = token
        params_step2['ts'] = str(int(time.time()))
        params_step2['_rticket'] = str(int(time.time() * 1000))

        url_step2 = f"https://{host}/passport/auth/available_ways/?" + urlencode(params_step2)

        signature_step2 = SignerPy.sign(params=url_step2, payload=None, version=4404)
        
        headers_step2 = {
            'User-Agent': "com.zhiliaoapp.musically.go/410203 (Linux; U; Android 14; ar; RMX3834; Build/UP1A.231005.007;tt-ok/3.12.13.44.lite-ul)",
            'x-ss-req-ticket': signature_step2.get('x-ss-req-ticket', ''),
            'x-ss-stub': signature_step2.get('x-ss-stub', ''),
            'x-gorgon': signature_step2.get("x-gorgon", ""),
            'x-khronos': signature_step2.get("x-khronos", ""),
            'x-tt-passport-csrf-token': cookies.get('passport_csrf_token', ''),
            'passport_csrf_token': cookies.get('passport_csrf_token', ''),
            'content-type': "application/x-www-form-urlencoded",
            'x-ss-dp': "1340",
            'sdk-version': "2",
            'x-tt-ultra-lite': "1",
        }

        res_step2 = requests.post(
            url_step2,
            headers=headers_step2,
            cookies=cookies,
            timeout=15,
        )
        
        response_json_step2 = res_step2.json()
  
        if 'success' in response_json_step2.get("message", ""):
            data_step2 = response_json_step2.get('data', {})
            
            return {
                'data': {
                    'has_email': data_step2.get('has_email', False),
                    'has_mobile': data_step2.get('has_mobile', False),
                    'has_oauth': data_step2.get('has_oauth', False),
                    'has_passkey': data_step2.get('has_passkey', False),
                    'oauth_platforms': data_step2.get('oauth_platforms', [])
                },
                'message': 'success',
                'host': host
            }
          
    except Exception:
        logger.debug("get_available_ways failed for host %s", host, exc_info=True)
    return None


def find_account_end_point(username, proxies=None):
    # iterate over the Hostnames list (dynamically loaded)
    for host in Hostnames:
        try:
            secret = secrets.token_hex(16)
            cookies = {
                "passport_csrf_token": secret,
                "passport_csrf_token_default": secret
            }

            params = {
                'request_tag_from': "h5",
                'manifest_version_code': "410203",
                '_rticket': str(int(time.time() * 1000)),
                'app_language': "ar",
                'app_type': "normal",
                'iid': str(random.randint(1, 10**19)),
                'app_package': "com.zhiliaoapp.musically.go",
                'channel': "googleplay",
                'device_type': "RMX3834",
                'language': "ar",
                'host_abi': "arm64-v8a",
                'locale': "ar",
                'resolution': "720*1454",
                'openudid': "b57299cf6a5bb211",
                'update_version_code': "410203",
                'ac2': "lte",
                'cdid': str(uuid.uuid4()),
                'sys_region': "EG",
                'os_api': "34",
                'timezone_name': "Asia/Baghdad",
                'dpi': "272",
                'carrier_region': "IQ",
                'ac': "4g",
                'device_id': str(random.randint(1, 10**19)),
                'os': "android",
                'os_version': "14",
                'timezone_offset': "10800",
                'version_code': "410203",
                'app_name': "musically_go",
                'ab_version': "41.2.3",
                'version_name': "41.2.3",
                'device_brand': "realme",
                'op_region': "IQ",
                'ssmix': "a",
                'device_platform': "android",
                'build_number': "41.2.3",
                'region': "EG",
                'aid': "1340",
                'ts': str(int(time.time())),
                'okhttp_version': "4.1.103.107-ul",
                'use_store_region_cookie': "1"
            }

            url = f"https://{host}/passport/find_account/tiktok_username/?" + urlencode(params)

            payload = {
                'mix_mode': "1",
                'username': username,
            }

            signature = SignerPy.sign(params=url, payload=payload, version=4404)

            headers = {
                'User-Agent': "com.zhiliaoapp.musically.go/410203 (Linux; U; Android 14; ar; RMX3834; Build/UP1A.231005.007;tt-ok/3.12.13.44.lite-ul)",
                'x-ss-req-ticket': signature.get('x-ss-req-ticket', ''),
                'x-ss-stub': signature.get('x-ss-stub', ''),
                'x-gorgon': signature.get("x-gorgon", ""),
                'x-khronos': signature.get("x-khronos", ""),
                'x-tt-passport-csrf-token': cookies.get('passport_csrf_token', ''),
                'passport_csrf_token': cookies.get('passport_csrf_token', ''),
                'content-type': "application/x-www-form-urlencoded",
                'x-ss-dp': "1340",
                'sdk-version': "2",
                'x-tt-ultra-lite': "1",
                'x-vc-bdturing-sdk-version': "2.3.15.i18n",
                'ttzip-tlb': "1",
            }

            response = requests.post(
                url,
                data=payload,
                headers=headers,
                cookies=cookies,
                timeout=15
            )
            try:
                data = response.json()
                if data.get('message') == 'success':
                    token = data["data"]["token"]
                    return get_available_ways(host, token, params, cookies, proxies)
            except Exception:
                logger.debug("find_account_end_point: failed to parse response json for host %s", host, exc_info=True)
        except Exception:
            logger.debug("find_account_end_point: exception for host %s", host, exc_info=True)
    return None


def info(username):
    headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Android 10; Pixel 3 Build/QKQ1.200308.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/125.0.6394.70 Mobile Safari/537.36 trill_350402 JsSdk/1.0 NetType/MOBILE Channel/googleplay AppName/trill app_version/35.3.1 ByteLocale/en ByteFullLocale/en Region/IN AppId/1180 Spark/1.5.9.1 AppVersion/35.3.1 BytedanceWebview/d8a21c6",
    }
    try:
        tikinfo = requests.get(f'https://www.tiktok.com/@{username}', headers=headers).text
        getting = str(tikinfo.split('webapp.user-detail"')[1]).split('"RecommendUserList"')[0]
        user_id = str(getting.split('id":"')[1]).split('",')[0]
        try:
            binary = "{0:b}".format(int(user_id))
            i = 0
            bits = ""
            while i < 31:
                bits += binary[i]
                i += 1
                timestamp = int(bits, 2)
                cdt = datetime.fromtimestamp(timestamp)
        except:
            cdt = ""
        try:
            username_modifytime_timestamp = str(getting.split('uniqueIdModifyTime":')[1]).split(',')[0]
            username_modifytime = datetime.fromtimestamp(int(username_modifytime_timestamp))
            swap_time = username_modifytime + timedelta(days=30)
        except:
            username_modifytime = ""
            swap_time = ""
        try:
            name = str(getting.split('nickname":"')[1]).split('",')[0]
        except:
            name = ""
        try:
            bio = str(getting.split('signature":"')[1]).split('",')[0]
        except:
            bio = ""
        try:
            country = str(getting.split('region":"')[1]).split('",')[0]
        except:
            country = "" 
        try:
            countryn = str(pycountry.countries.get(alpha_2=country)).split("name='")[1].split("'")[0]
        except:
            countryn = ""
        try:
            countryf = str(pycountry.countries.get(alpha_2=country)).split("flag='")[1].split("'")[0]    
        except:
            countryf = ""    
        try:
            private = str(getting.split('privateAccount":')[1]).split(',')[0]
        except:
            private = ""
        try:
            followers = str(getting.split('followerCount":')[1]).split(',')[0]
        except:
            followers = "" 
        try:
            following = str(getting.split('followingCount":')[1]).split(',')[0]
        except:
            following = ""
        try:
            like = str(getting.split('heart":')[1]).split(',')[0]
        except:
            like = ""
        try:
            video = str(getting.split('videoCount":')[1]).split(',')[0]
        except:
            video = ""
        try:
            avatar = str(getting.split('avatarThumb":"')[1]).split('",')[0]
        except:
            avatar = ""
        if avatar:
            avatar = codecs.decode(avatar, 'unicode_escape')

        return {
            'user_id': user_id,
            'cdt': cdt,
            'username_modifytime': username_modifytime,
            'countryn': countryn,
            'countryf': countryf,
            'name': name,
            'bio': bio,
            'country': country,
            'private': private,
            'followers': followers,
            'following': following,
            'like': like,
            'video': video,
            'avatar': avatar
        }
    except Exception:
        logger.debug("info() failed for username %s", username, exc_info=True)
        return None


def sign_level(params, payload: str = None, sec_device_id: str = "", cookie: str or None = None, aid: int = 1233, license_id: int = 1611921764, sdk_version_str: str = "2.3.1.i18n", sdk_version: int = 2, platform: int = 19, unix: int = None):
    x_ss_stub = md5(payload.encode('utf-8')).hexdigest() if payload != None else None
    if not unix:
        unix = int(time.time())
    return Gorgon(params, unix, payload, cookie).get_value() | {
        "x-ladon": Ladon.encrypt(unix, license_id, aid),
        "x-argus": Argus.get_sign(params, x_ss_stub, unix, platform=platform, aid=aid, license_id=license_id, sec_device_id=sec_device_id, sdk_version=sdk_version_str, sdk_version_int=sdk_version)
    }


def get_level(username):
    user_info = info(username)
    user_id = user_info['user_id'] if user_info else None
    if not user_id:
        return None

    # Use a EU webcast endpoint by default to try to get EU-levels.
    url = "https://webcast16-normal-no1a.tiktokv.eu/webcast/user/?request_from=profile_card_v2&request_from_scene=1&target_uid=" + \
        str(user_id)+"&iid="+str(random.randint(1, 10**19))+"&device_id="+str(random.randint(1, 10**19))+"&ac=wifi&channel=googleplay&aid=1233&app_name=musical_ly&version_code=300102&version_name=30.1.2&device_platform=android&os=android&ab_version=30.1.2&ssmix=a&device_type=RMX3511&device_brand=realme&language=ar&os_api=33&os_version=13&openudid="+str(binascii.hexlify(os.urandom(8)).decode())+"&manifest_version_code=2023001020&resolution=1080*2236&dpi=360&update_version_code=2023001020&_rticket="+str(round(random.uniform(
            1.2, 1.6) * 100000000) * -1) + "4632"+"&current_region=IQ&app_type=normal&sys_region=IQ&mcc_mnc=41805&timezone_name=Asia%2FBaghdad&carrier_region_v2=418&residence=IQ&app_language=ar&carrier_region=IQ&ac2=wifi&uoo=0&op_region=IQ&timezone_offset=10800&build_number=30.1.2&host_abi=arm64-v8a&locale=ar&region=IQ&content_language=gu%2C&ts="+str(round(random.uniform(1.2, 1.6) * 100000000) * -1)+"&cdid="+str(uuid.uuid4())+"&webcast_sdk_version=2920&webcast_language=ar&webcast_locale=ar_IQ"
    headers = {
        'User-Agent': "com.zhiliaoapp.musically/2023001020 (Linux; U; Android 13; ar; RMX3511; Build/TP1A.220624.014; Cronet/TTNetVersion:06d6a583 2023-04-17 QuicVersion:d298137e 2023-02-13)"}
    headers.update(sign_level(url.split('?')[1], '', "AadCFwpTyztA5j9L" + ''.join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(9)), None, 1233))

    try:
        response = requests.get(url, headers=headers)
        match = re.search(r'"default_pattern":"(.*?)"', response.text)
        if match:
            return match.group(1)
    except Exception:
        logger.debug("get_level() failed for username %s", username, exc_info=True)
    return None


# ---------------- CLI generation support (when running module directly) ----------------
def _cli_generate():
    parser = argparse.ArgumentParser(description="Generate hosts.txt (integrated in oouss.py)")
    parser.add_argument("--start", type=int, default=0, help="start number for pattern expansion (inclusive)")
    parser.add_argument("--end", type=int, default=199, help="end number for pattern expansion (inclusive)")
    parser.add_argument("--outfile", type=str, default=HOSTS_FILE, help="output file path")
    parser.add_argument("--max", type=int, default=5000, help="maximum hosts to write")
    parser.add_argument("--resolve", action="store_true", help="attempt to resolve hosts and keep only resolvable ones (slower)")
    parser.add_argument("--concurrency", type=int, default=40, help="concurrency for DNS resolution")
    args = parser.parse_args()

    extra = DEFAULT_BASE_HOSTS.copy()
    hosts = generate_hosts(args.start, args.end, extra_hosts=extra, max_count=args.max, resolve=args.resolve, concurrency=args.concurrency)
    write_hosts_file(hosts, args.outfile)
    print(f"Wrote {len(hosts)} hosts to {args.outfile}")


if __name__ == "__main__":
    # If module executed directly, offer CLI to generate hosts.txt
    _cli_generate()