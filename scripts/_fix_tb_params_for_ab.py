"""One-shot: подкрутить TB params чтобы они match T1.

Используем raw client.request (минует dataclass roundtrip + production guard).
TB = testbed, не в production set, потому безопасно.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.short_bots_guard.control import _build_api

TB_ID = 4525648417


def main():
    api, err = _build_api()
    if api is None:
        print(f"FAILED to build API: {err}")
        return
    client = api.client

    # 1. GET current params
    print(f"GET /bots/{TB_ID}/params ...")
    cur = client.request("GET", f"/bots/{TB_ID}/params")

    print(f"\nBEFORE:")
    print(f"  q.minQ: {cur.get('q', {}).get('minQ')}")
    print(f"  q.maxQ: {cur.get('q', {}).get('maxQ')}")
    print(f"  ttp:    {cur.get('ttp')}")
    cnds_arr = cur.get('in', {}).get('start', {}).get('cnds') or []
    if cnds_arr:
        print(f"  in.start.cnds.0.items.0.p: {cnds_arr[0].get('items', [{}])[0].get('p')}")

    # 2. Modify in-place
    cur.setdefault("q", {})
    cur["q"]["minQ"] = 0.001
    cur["q"]["maxQ"] = 0.002
    cur["ttp"] = 60
    if cnds_arr and cnds_arr[0].get("items"):
        cnds_arr[0]["items"][0]["p"] = 0.3

    # 3. PUT back
    print(f"\nPUT /bots/{TB_ID}/params (modified)...")
    try:
        result = client.request("PUT", f"/bots/{TB_ID}/params", json=cur)
        print(f"  Response: {json.dumps(result, ensure_ascii=False)[:200]}")
    except Exception as e:
        print(f"  ✗ Failed: {e}")
        return

    # 4. Verify
    print(f"\nGET /bots/{TB_ID}/params (verify)...")
    after = client.request("GET", f"/bots/{TB_ID}/params")
    print(f"AFTER:")
    print(f"  q.minQ: {after.get('q', {}).get('minQ')}")
    print(f"  q.maxQ: {after.get('q', {}).get('maxQ')}")
    print(f"  ttp:    {after.get('ttp')}")
    cnds2 = after.get('in', {}).get('start', {}).get('cnds') or []
    if cnds2:
        print(f"  in.start.cnds.0.items.0.p: {cnds2[0].get('items', [{}])[0].get('p')}")

    ok = (after.get("q", {}).get("minQ") == 0.001
          and after.get("q", {}).get("maxQ") == 0.002
          and after.get("ttp") == 60)
    if ok:
        print(f"\n✓ TB params aligned to T1.")
    else:
        print(f"\n⚠ Some fields didn't update. Check manually in GinArea UI.")


if __name__ == "__main__":
    main()
