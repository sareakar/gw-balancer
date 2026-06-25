#!/usr/bin/env python3
"""AGI script: consulta el Core Engine y setea GWB_GATEWAY en el canal de Asterisk.

Dialplan de ejemplo:
  exten => _X.,1,AGI(agi_route.py)
  same  => n,GotoIf($["${GWB_GATEWAY}" = ""]?fallback)
  same  => n,Dial(SIP/${EXTEN}@${GWB_GATEWAY})
  same  => n(fallback),Dial(SIP/${EXTEN}@fallback-trunk)

Variables de entorno requeridas:
  GWB_CORE_URL  — URL del Core Engine (ej: https://core.gwbalancer.example.com)
  GWB_API_KEY   — API key del adaptador
"""
import json
import os
import sys
import urllib.error
import urllib.request

CORE_URL = os.getenv("GWB_CORE_URL", "http://localhost:8000")
API_KEY = os.getenv("GWB_API_KEY", "")
TIMEOUT = float(os.getenv("GWB_TIMEOUT", "2"))


def _read_agi_env() -> dict[str, str]:
    env = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            break
        if ":" in line:
            k, v = line.split(":", 1)
            env[k.strip()] = v.strip()
    return env


def _agi(cmd: str) -> str:
    sys.stdout.write(cmd + "\n")
    sys.stdout.flush()
    return sys.stdin.readline().strip()


def agi_set_var(name: str, value: str):
    _agi(f"SET VARIABLE {name} {value}")


def agi_verbose(msg: str):
    _agi(f'VERBOSE "{msg}" 1')


def main():
    agi_env = _read_agi_env()
    call_id = agi_env.get("agi_uniqueid", "")

    agi_verbose(f"GWB: requesting route for call {call_id}")

    payload = json.dumps({"call_id": call_id}).encode()
    req = urllib.request.Request(
        f"{CORE_URL}/v1/route-decision",
        data=payload,
        headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
    )

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            decision = json.loads(resp.read())

        gateway_slug = decision["gateway_slug"]
        score = decision["score"]
        agi_verbose(f"GWB: selected {gateway_slug} (score={score})")
        agi_set_var("GWB_GATEWAY", gateway_slug)
        agi_set_var("GWB_SCORE", str(score))

    except urllib.error.URLError as exc:
        agi_verbose(f"GWB: core engine unreachable: {exc}")
        agi_set_var("GWB_GATEWAY", "")
    except Exception as exc:
        agi_verbose(f"GWB: unexpected error: {exc}")
        agi_set_var("GWB_GATEWAY", "")


if __name__ == "__main__":
    main()
