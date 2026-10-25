# -*- coding: utf-8 -*-
"""validity.py — 记忆时效图谱（Graphiti 思想的轻量实现）
================================================================
用户需求（2026-10-25）："记忆层可借鉴的升级做了吗，没做就做"
来源：Graphiti（Zep 开源核心）的时序知识图谱——边带 valid_at/invalid_at 时间戳

核心思想：**结论不删除，但带有效时间窗**。
  - recall 命中一条已失效的记忆 → 自动标注 ⚠️已失效 + 指向新结论
  - 防止陈旧记忆误导（如 R21 动态杠杆已证伪，若被再次引用必须提示）

存储：<ROOT>/knowledge/记忆时效图谱.json
结构：entries[] = {id, claim, status, valid_from, invalid_at, superseded_by, source, keywords}

API：
  load()                      读图谱
  add(entry)                  新增/更新条目
  invalidate(id, superseded_by)  标记失效（不删数据——用户定调"不修剪"）
  check(text)                 给一段检索结果，返回其中命中的失效条目
  from_supersede(old, new, reason)  对接 decision-gate 的 dg_supersede
"""
import os
import re
import json
import time

try:
    from config import ROOT
except Exception:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

GRAPH = os.path.join(ROOT, "knowledge", "记忆时效图谱.json")


def _now():
    return time.strftime("%Y-%m-%d")


def load():
    if not os.path.exists(GRAPH):
        return {"version": 1, "entries": []}
    try:
        return json.load(open(GRAPH, encoding="utf-8"))
    except Exception:
        return {"version": 1, "entries": []}


def save(g):
    os.makedirs(os.path.dirname(GRAPH), exist_ok=True)
    g["version"] = g.get("version", 1)
    g["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    json.dump(g, open(GRAPH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def add(entry_id, claim, status="valid", valid_from=None, superseded_by="",
        source="", keywords=None):
    """新增/更新条目。status: valid | invalid | superseded"""
    g = load()
    e = {
        "id": entry_id,
        "claim": claim,
        "status": status,
        "valid_from": valid_from or _now(),
        "invalid_at": _now() if status != "valid" else "",
        "superseded_by": superseded_by,
        "source": source,
        "keywords": keywords or [],
    }
    for i, old in enumerate(g["entries"]):
        if old.get("id") == entry_id:
            g["entries"][i] = e
            break
    else:
        g["entries"].append(e)
    save(g)
    return e


def invalidate(entry_id, superseded_by="", reason=""):
    """标记失效（数据保留，只改状态——与用户"不修剪"定调一致）"""
    g = load()
    for e in g["entries"]:
        if e.get("id") == entry_id:
            e["status"] = "invalid"
            e["invalid_at"] = _now()
            if superseded_by:
                e["superseded_by"] = superseded_by
            if reason:
                e["reason"] = reason
            save(g)
            return e
    return None


def check(text, max_hits=5):
    """检查一段文本命中哪些失效条目（recall 时调用，给 AI 提示"别用这个"）"""
    g = load()
    hits = []
    t = str(text or "")
    for e in g["entries"]:
        if e.get("status") == "valid":
            continue
        kws = [k for k in (e.get("keywords") or []) if k]
        if not kws:
            # 无关键词则用 claim 的前 12 字
            kws = [e.get("claim", "")[:12]]
        if any(k in t for k in kws if len(k) >= 2):
            hits.append({
                "id": e["id"], "claim": e.get("claim"),
                "invalid_at": e.get("invalid_at"),
                "superseded_by": e.get("superseded_by"),
            })
            if len(hits) >= max_hits:
                break
    return hits


def seed_from_memory():
    """从 MEMORY.md 已知的取代链播种初始图谱（一次性，幂等）"""
    seeds = [
        ("r21-dynamic-leverage", "regime 动态杠杆优于固定杠杆", "invalid",
         "固定杠杆夏普 3.38 恒定 > regime 动态 2.68（R21 实测证伪）",
         "MEMORY.md §7", ["动态杠杆", "regime 杠杆"]),
        ("v39-e3", "V39/E3 策略有效", "invalid",
         "前视/泄漏，作废", "MEMORY.md §7", ["V39", "E3"]),
        ("r16-r17-pressure", "R16/R17 压力位类策略", "invalid",
         "全证伪", "MEMORY.md §7", ["R16", "R17", "压力位"]),
        ("directional-alpha-2026", "crypto 方向性 alpha 2026 可交易", "invalid",
         "方向性 alpha 2026 消失，简单多头规则=beta 加速器", "MEMORY.md §7",
         ["方向性 alpha", "简单多头"]),
        ("trend-daily-tp", "trend_daily 固定 TP 出场", "invalid",
         "-90.6% 结构性错误（08-23 事故），P0-3 SL-only 安全路径", "MEMORY.md 工作背景",
         ["trend_daily", "固定 TP"]),
        ("shadow-log-eval", "影子日志样本可直接评估", "invalid",
         "禁影子日志样本评估 → 完整 5m 路径重放", "MEMORY.md §5", ["影子日志"]),
        ("r18-3rn-trend-guard", "trend_guard 24h 实盘直接部署", "invalid",
         "实盘小样本结论必须回测 6 年复核（R18-3rN：-104bp 部署后回测证伪回滚）",
         "MEMORY.md §6", ["trend_guard"]),
        ("orderflow-1m", "订单流 1m 信号可交易", "invalid",
         "订单流 3 年全证伪（成本死结），cvd_slope15 待 15m/1h 升级", "MEMORY.md §7",
         ["订单流", "OBI"]),
    ]
    n = 0
    for eid, claim, status, sup, src, kws in seeds:
        g = load()
        if any(x.get("id") == eid for x in g["entries"]):
            continue
        add(eid, claim, status=status, superseded_by=sup, source=src, keywords=kws)
        n += 1
    return n


def stats():
    g = load()
    ent = g.get("entries", [])
    return {"total": len(ent),
            "invalid": sum(1 for e in ent if e.get("status") != "valid"),
            "valid": sum(1 for e in ent if e.get("status") == "valid")}


def from_supersede(old_id, new_conclusion, reason=""):
    """对接 decision-gate 的 dg_supersede：旧结论标记失效并指向新结论"""
    e = invalidate(old_id, superseded_by=new_conclusion, reason=reason)
    if e is None:
        # 旧条目不在图谱里 → 用 old_id 当 claim 补一条
        add(old_id, old_id, status="invalid", superseded_by=new_conclusion)
        e = {"id": old_id, "claim": old_id}
    return e


if __name__ == "__main__":
    import sys
    if "--seed" in sys.argv:
        n = seed_from_memory()
        print(f"播种 {n} 条失效记录（幂等）")
    print(json.dumps(stats(), ensure_ascii=False))
    # 演示 check
    demo = "我们用 R21 动态杠杆方案加仓"
    hits = check(demo)
    print(f"\ncheck({demo!r}) → {json.dumps(hits, ensure_ascii=False)}")
