#!/usr/bin/env python3
"""
MedoSigner.py - lightweight stub for Argus, Gorgon, md5, Ladon used by oouss.py.

This stub provides minimal functions/classes to satisfy imports. It does NOT
produce real signatures — install the real MedoSigner/related package for production.
"""

import hashlib
from typing import Dict, Any, Optional

class Argus:
    @staticmethod
    def get_sign(params: str, x_ss_stub: Optional[str], unix: int, **kwargs) -> str:
        # Return a placeholder string to satisfy callers.
        return "argus_stub"

class Gorgon:
    def __init__(self, params: str, unix: int, payload: Optional[str] = None, cookie: Optional[str] = None):
        self._params = params
        self._unix = unix
        self._payload = payload
        self._cookie = cookie

    def get_value(self) -> Dict[str, str]:
        # Minimal mapping expected by callers
        return {"x-gorgon": "gorgon_stub", "x-khronos": str(int(self._unix))}

def md5(b: bytes):
    # return an object with hexdigest method (mimic hashlib.md5)
    class _MD5:
        def __init__(self, b):
            self._h = hashlib.md5(b)
        def hexdigest(self):
            return self._h.hexdigest()
    return _MD5(b)

class Ladon:
    @staticmethod
    def encrypt(unix: int, license_id: int, aid: int) -> str:
        return "ladon_stub"