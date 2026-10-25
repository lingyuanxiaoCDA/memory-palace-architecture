# -*- coding: utf-8 -*-
"""laya_alert.py — LAYA 告警分类器（System 1 决策模型）
================================================================
依据 2026-09-24 实测：alert.category 准确率 0.833 vs 基线 0.250（+0.583），ECE 0.053
用法：
  from laya_alert import classify
  r = classify("订单提交失败: 51008 Insufficient USDT")
  # → {"category": "execution_failure", "category_conf": 0.87, "needs_action": true,
  #     "priority": "P1", "ms": 42.1}

命令行：
  python laya_alert.py "告警文本"
  python laya_alert.py --stdin     # 从 stdin 读（批量逐行）
"""
from config import (ROOT, AUTONOMY, SESSIONS, EXPERIENCE, NOTES,
                     MEMORY_MD, LESSONS, DIARY, LOG_DIR, CHROMA_DB,
                     SQLITE_DB, WING_KEYWORDS, SERVICES, MINE_INTERVAL,
                     CACHE_MAX, MEMPALACE_CLI, LLM_ENDPOINT, LLM_MODEL, LLM_KEY,
                     PORT_MEM_SERVICE, PORT_HUB)
import sys, os, json, argparse

LAYA_DIR = os.environ.get("MP_LAYA_DIR", "laya")
if LAYA_DIR not in sys.path:
    sys.path.insert(0, LAYA_DIR)

_checker = None


def _get_checker(checkpoint="english"):
    """延迟加载（首次 ~10s，之后复用）"""
    global _checker
    if _checker is None:
        from checker import LayaChecker
        _checker = LayaChecker(checkpoint=checkpoint)
    return _checker


def classify(alert_text, checkpoint="english"):
    """单条告警分类
    返回: category(6类) / category_conf / needs_action(bool) / priority(P0-P3) / ms
    """
    if not alert_text or not str(alert_text).strip():
        return {"error": "空告警文本"}
    try:
        import questions as Q
        ck = _get_checker(checkpoint)
        r = ck.check(Q.get("alert"), {"alert": str(alert_text)[:4000]}, scenario_key="alert")
    except Exception as e:
        return {"error": "%s: %s" % (type(e).__name__, str(e)[:150])}
    if not r.get("ok"):
        return {"error": r.get("error") or "unknown"}
    f = r.get("fields") or {}
    out = {"ms": round(r.get("ms", 0), 1), "checkpoint": checkpoint}
    for k in ("category", "needs_action", "priority"):
        if k in f:
            v = f[k]
            out[k] = v.get("answer")
            out[k + "_conf"] = round(float(v.get("conf") or 0), 3)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default="")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--checkpoint", default="english")
    args = ap.parse_args()

    if args.stdin:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            r = classify(line, args.checkpoint)
            r["alert"] = line[:100]
            print(json.dumps(r, ensure_ascii=False))
    else:
        if not args.text:
            print("用法: python laya_alert.py \"告警文本\"  或  --stdin")
            return
        r = classify(args.text, args.checkpoint)
        print(json.dumps(r, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
