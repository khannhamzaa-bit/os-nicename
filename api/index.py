"""
OB55 FreeFire API — Vercel Serverless (FastAPI)
"""
import time, random, requests
from typing import Dict, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==================== Constants ====================
AES_KEY = bytes([89, 103, 38, 116, 99, 37, 68, 69, 117, 104, 54, 37, 90, 99, 94, 56])
AES_IV  = bytes([54, 111, 121, 90, 68, 114, 50, 50, 69, 51, 121, 99, 104, 106, 77, 37])

VERSION_API_URL = "https://version.freefireind.in"
JWT_API_URL     = "https://os-jwt-access.vercel.app/api/public/token"
NICKNAME_PATH   = "/MajorModifyNickname"

FALLBACK_CONFIG = {
    "IND":     {"client_url": "https://client.ind.freefiremobile.com/", "server_url": "https://loginbp.ppmainecoonghj.com/", "release_version": "OB55", "client_version": "1.132.16"},
    "AMERICA": {"client_url": "https://client.us.freefiremobile.com/",  "server_url": "https://loginbp.ppmainecoonghj.com/", "release_version": "OB55", "client_version": "1.132.16"},
    "OTHERS":  {"client_url": "https://clientbp.ppmainecoonghj.com/",   "server_url": "https://loginbp.ppmainecoonghj.com/", "release_version": "OB55", "client_version": "1.132.16"},
}

# ==================== Crypto ====================
def encrypt_data(data: bytes) -> bytes:
    return AES.new(AES_KEY, AES.MODE_CBC, AES_IV).encrypt(pad(data, AES.block_size))

def decrypt_data(data: bytes) -> bytes:
    return unpad(AES.new(AES_KEY, AES.MODE_CBC, AES_IV).decrypt(data), AES.block_size)

# ==================== Protobuf ====================
def encode_varint(n: int) -> bytes:
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)

def build_nickname_payload(nickname: str) -> bytes:
    nb = nickname.encode("utf-8")
    return (encode_varint(10) + encode_varint(len(nb)) + nb) + encode_varint(16) + encode_varint(1)

# ==================== Version cache (per warm lambda) ====================
_cache = {"data": None, "ts": 0}

def fetch_version_config(force: bool = False) -> Dict:
    now = time.time()
    if not force and _cache["data"] and now - _cache["ts"] < 300:
        return _cache["data"]
    try:
        r = requests.get(VERSION_API_URL, timeout=8)
        if r.status_code == 200:
            _cache["data"] = r.json()
            _cache["ts"] = now
            return _cache["data"]
    except Exception:
        pass
    return _cache["data"] or FALLBACK_CONFIG

def get_region_config(region: str) -> Dict:
    cfg = fetch_version_config()
    r = (region or "OTHERS").upper()
    if r in cfg: return cfg[r]
    if r in ("IN", "INDIA"):                    return cfg.get("IND")     or cfg["OTHERS"]
    if r in ("US", "NA", "BR", "SA", "LATAM"):  return cfg.get("AMERICA") or cfg["OTHERS"]
    return cfg.get("OTHERS") or FALLBACK_CONFIG["OTHERS"]

# ==================== JWT ====================
def fetch_jwt(uid: str, password: str) -> Dict:
    try:
        r = requests.get(JWT_API_URL, params={"uid": str(uid), "password": password}, timeout=12)
        if r.status_code != 200:
            return {"error": f"HTTP {r.status_code}", "detail": r.text[:200]}
        d = r.json()
        if not d.get("token"):
            return {"error": "No token", "detail": d}
        return d
    except Exception as e:
        return {"error": str(e)}

# ==================== Nickname ====================
def change_nickname(jwt: str, nickname: str, region: str = "OTHERS") -> Dict:
    cfg = get_region_config(region)
    url = cfg["server_url"].rstrip("/") + NICKNAME_PATH
    body = encrypt_data(build_nickname_payload(nickname))
    headers = {
        "User-Agent": "UnityPlayer/2022.3.47f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": cfg["release_version"],
        "Content-Type": "application/octet-stream",
        "X-Unity-Version": "2022.3.47f1",
    }
    try:
        r = requests.post(url, headers=headers, data=body, verify=False, timeout=15)
        return {"status": r.status_code, "raw": r.content, "url": url}
    except Exception as e:
        return {"status": 0, "raw": b"", "error": str(e), "url": url}

def generate_nickname(base: str, used: set) -> str:
    for _ in range(100):
        s = str(random.randint(1000, 999999))
        cand = base + s
        if len(cand) > 12:
            cand = base[:12 - len(s)] + s
        if cand not in used:
            used.add(cand)
            return cand
    raise RuntimeError("Could not generate nickname.")

# ==================== FastAPI app ====================
app = FastAPI(title="OB55 FreeFire API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

class NickReq(BaseModel):
    uid: str
    password: str
    new_nickname: str

class BatchReq(BaseModel):
    accounts: List[Dict]
    base_name: str

@app.get("/")
def root():
    return {
        "service": "OB55 FreeFire API",
        "release": "OB55",
        "endpoints": {
            "GET  /regions": "Live region configs",
            "GET  /token?uid=&password=": "Fetch JWT",
            "POST /nickname": "Change nickname (auto region)",
            "POST /batch": "Batch change (may timeout on Hobby plan)",
            "GET  /health": "Health check",
        },
    }

@app.get("/health")
def health():
    return {"ok": True, "ts": int(time.time())}

@app.get("/regions")
def regions():
    return fetch_version_config(force=True)

@app.get("/token")
def token(uid: str, password: str):
    r = fetch_jwt(uid, password)
    if "error" in r:
        raise HTTPException(400, detail=r)
    return r

@app.post("/nickname")
def nickname(req: NickReq):
    j = fetch_jwt(req.uid, req.password)
    if "error" in j:
        raise HTTPException(400, detail=j)
    region = j.get("region", "OTHERS")
    res = change_nickname(j["token"], req.new_nickname, region)
    if res["status"] != 200:
        raise HTTPException(res["status"] or 500, detail={
            "message": "Nickname change failed",
            "error": res.get("error"),
            "raw_hex": res["raw"].hex()[:200] if res["raw"] else None,
        })
    return {
        "success": True,
        "uid": req.uid,
        "account_id": j.get("account_id"),
        "region": region,
        "new_nickname": req.new_nickname,
        "release_version": get_region_config(region)["release_version"],
    }

@app.post("/batch")
def batch(req: BatchReq):
    used, out = set(), []
    for i, acc in enumerate(req.accounts, 1):
        uid = str(acc.get("uid", ""))
        pwd = acc.get("password", "")
        if not uid or not pwd:
            out.append({"index": i, "uid": uid, "status": "skipped", "reason": "missing"}); continue
        j = fetch_jwt(uid, pwd)
        if "error" in j:
            out.append({"index": i, "uid": uid, "status": "jwt_failed", "error": j}); continue
        region = j.get("region", "OTHERS")
        try:
            nn = generate_nickname(req.base_name, used)
        except Exception as e:
            out.append({"index": i, "uid": uid, "status": "gen_failed", "error": str(e)}); continue
        res = change_nickname(j["token"], nn, region)
        out.append({
            "index": i, "uid": uid, "region": region,
            "status": "success" if res["status"] == 200 else "failed",
            "new_nickname": nn if res["status"] == 200 else None,
            "http": res["status"],
        })
    return {
        "total": len(req.accounts),
        "success": sum(1 for x in out if x["status"] == "success"),
        "results": out,
    }

# Vercel expects a module-level "handler" alias for some setups
handler = app
