# -*- coding: utf-8 -*-
"""recall_router.py — 记忆检索路由层（决策模型的前置规则版）
================================================================
用户架构（2026-10-25）：
  LLM 需求 → 判断属于哪个 wing（19 个）→ mempalace_search(wing) → 结果
  → 记录日志（为 LAYA 微调积累标注）

两阶段：
  v0（现在）：关键词规则路由（快、可解释、零依赖）
  v1（未来）：LAYA 学这个 19 分类（用本模块日志做标注集）

日志格式（JSONL，每条 = 一条训练标注）：
  {"ts":..., "need":"...", "wings":[...], "hit":true/false, "source":"rule|llm"}

用法：
  from recall_router import route_and_search
  r = route_and_search("V37 的 dr 验证结论")
  print(r["answer"])

  python recall_router.py "查询文本"
"""
import os, re, json, time, sqlite3
try:
    from config import (LOG_DIR, CHROMA_DB, SQLITE_DB, AUTONOMY, ROOT,
                        WING_KEYWORDS, MEMPALACE_CLI)
except Exception:
    LOG_DIR = os.path.join(os.path.expanduser("~"), ".memory-palace", "tmp")
    CHROMA_DB = os.path.join(os.path.expanduser("~"), ".memory-palace", "palace", "chroma.sqlite3")
    SQLITE_DB = os.path.join(os.path.expanduser("~"), ".memory-palace", "agent_memory.db")
    AUTONOMY = os.path.join(os.path.expanduser("~"), ".memory-palace", "autonomy")
    ROOT = os.path.join(os.path.expanduser("~"), ".memory-palace")
    WING_KEYWORDS = {}
    MEMPALACE_CLI = "mempalace"


BASE = os.path.dirname(os.path.abspath(__file__))
PALACE = os.path.dirname(CHROMA_DB)
CHROMA = os.path.join(PALACE, "chroma.sqlite3")
LOG = os.path.join(LOG_DIR, "recall_router.log.jsonl")

# 19 个 wing → 触发关键词（来自 mempalace_status 实测）
WING_KEYWORDS = {
    "策略方法论": ["策略", "r18", "回测", "夏普", "回撤", "pf", "oos", "胜率", "盈亏比", "参数", "闸门", "反过拟合"],
    "ai_trading": ["实盘", "下单", "okx", "仓位", "杠杆", "止损", "止盈", "爆仓", "保证金", "交易所"],
    "量化研究": ["因子", "特征", "样本", "相关性", "spearman", "ic", "alpha", "信号", "k线", "指标"],
    "quant-r18": ["r18", "双腿", "5m", "30m", "解锁", "触障", "sigma", "宽障碍"],
    "r18": ["r18", "conf", "门槛", "熔断"],
    "autonomy": ["凌麒", "自主", "心跳", "决策", "漂移", "审计", "会话", "节点"],
    "工作记忆": ["工作日志", "任务", "进度", "待办", "交接"],
    "knowledge": ["结论", "审计", "配置卡", "溯源", "状态表", "铁律"],
    "学习中心": ["速查", "教程", "笔记", "学习方法", "错误档案"],
    "用户档案": ["用户", "偏好", "习惯", "身份"],
    "个人工作流": ["工作流", "流程", "规范"],
    "ai视频生成": ["视频", "comfyui", "h3", "模型", "渲染"],
    "剪辑建模": ["剪辑", "建模", "blender", "daz"],
    "文学创作": ["小说", "写作", "剧情", "角色"],
    "palace_docs": ["mempalace", "记忆宫殿", "drawer", "closet"],
    "harness": ["harness", "dsh", "插件"],
    "notes": ["笔记"],
    "staging": ["暂存"],
    "r18_mine_dir": ["r18"],
}

STOP = set("的 了 是 在 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没有 看 好 自 己 这 那 它 他 她 请问 帮我 怎么 什么".split())


def _log(rec):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + chr(10))
    except Exception:
        pass


def route(need, topk=2):
    """需求 → 候选 wing 列表（关键词打分）"""
    low = (need or "").lower()
    scores = {}
    for wing, kws in WING_KEYWORDS.items():
        s = 0
        for kw in kws:
            if kw in low:
                s += 3 if len(kw) >= 4 else 2
        if s:
            scores[wing] = scores.get(wing, 0) + s
    ranked = sorted(scores.items(), key=lambda x: -x[1])[:topk]
    return [w for w, _ in ranked], ranked


TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{1,}|[一-鿿]{2,}")


def _terms(need, top=8):
    """分词：jieba（中文语义分词）优先，regex 兜底；去停用词"""
    seen = []
    try:
        import jieba
        for w in jieba.lcut(str(need or "")):
            w = w.strip()
            if not w or w.lower() in STOP or len(w) < 2:
                continue
            if w not in seen:
                seen.append(w)
    except Exception:
        pass
    if not seen:                       # jieba 失败 → regex 兜底
        for mm in TERM_RE.finditer(need or ""):
            w = mm.group(0)
            if w.lower() in STOP:
                continue
            if len(w) < 3 and not re.match(r"[一-鿿]", w):
                continue
            if w not in seen:
                seen.append(w)
    return seen[:top]



def _search_db(kw, wing=None, limit=5, use_bm25=True):
    """分词 OR 检索 + 命中词数排序（比整串 LIKE 实用得多）"""
    if not os.path.exists(CHROMA):
        return []
    terms = _terms(kw)
    if not terms:
        return []
    try:
        con = sqlite3.connect("file:" + CHROMA + "?mode=ro", uri=True)
    except Exception:
        return []
    out = []
    try:
        ors = " OR ".join(["md.string_value LIKE ?"] * len(terms))
        cond = "md.key='chroma:document' AND md.string_value NOT LIKE '%→drawer_%' AND (" + ors + ")"
        params = ["%" + t + "%" for t in terms]
        if wing:
            cond += " AND mw.string_value=?"
            params.append(wing)
        sql = ("SELECT md.string_value, ms.string_value, mw.string_value "
               "FROM embedding_metadata md "
               "LEFT JOIN embedding_metadata ms ON ms.id=md.id AND ms.key='source_file' "
               "LEFT JOIN embedding_metadata mw ON mw.id=md.id AND mw.key='wing' "
               "WHERE " + cond + " LIMIT 200")
        rows = con.execute(sql, params).fetchall()
        scored = []
        for doc, src, w in rows:
            d = str(doc)
            score = sum(d.count(t) for t in terms)
            if score > 0:
                scored.append((score, d, str(src or ""), str(w or "")))
        scored.sort(key=lambda x: -x[0])
        for score, d, src, w in scored[:max(1, min(int(limit), 30))]:
            out.append({"text": d[:800], "source": src, "wing": w, "score": score})
    except Exception:
        pass
    con.close()
    return out


def route_and_search(need, limit=5, log=True):
    """三步：模型优先 → 规则兜底 → 全局兜底 → 记录标注
    模型（train_router 连带训练产出）不确定时自动回落规则路由 —— 这就是"混合裁决"。
    """
    t0 = time.time()
    # ① SetFit 优先（语义级，实测 9/10；少样本 8 条/类即用）
    pred = None
    try:
        import train_router
        pred = train_router.predict_setfit(need)
        if pred:
            pred["model"] = "setfit"
    except Exception:
        pred = None
    # ② TF-IDF 次之（词级，快；SetFit 没加载/不确定时顶上）
    if pred is None:
        try:
            import train_router
            pred = train_router.predict(need)
            if pred:
                pred["model"] = "tfidf"
        except Exception:
            pred = None
    if pred:
        wings = [pred["wing"]]
        ranked = [(pred["wing"], pred.get("conf", 0))]
        source = pred.get("model", "model")
    else:
        wings, ranked = route(need)
        source = "rule"
    results = []
    used_wing = None
    # ① 按候选 wing 检索
    for w in wings:
        r = _search_db(need, wing=w, limit=limit)
        if r:
            results = r
            used_wing = w
            break
    # ② 兜底：全局检索
    if not results:
        results = _search_db(need, wing=None, limit=limit)
        used_wing = "global"
    hit = bool(results)
    out = {
        "need": need,
        "route_wings": wings,
        "route_scores": ranked,
        "used_wing": used_wing,
        "hit": hit,
        "n": len(results),
        "ms": round((time.time() - t0) * 1000, 1),
        "results": results,
    }
    if hit:
        out["answer"] = "\n\n".join(
            "[%s] %s" % (r["wing"] or "?", r["text"][:400]) for r in results[:3])
    else:
        out["answer"] = "（未找到相关记忆，可换关键词或确认是否已 mine）"
    if log:
        _log({"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "need": need,
              "wings": wings, "used": used_wing, "hit": hit, "n": len(results),
              "source": source, "model_conf": (pred or {}).get("conf"), "ms": out["ms"]})
    return out


def stats():
    """检索日志统计（LAYA 训练数据规模）"""
    if not os.path.exists(LOG):
        return {"total": 0}
    total = hit = 0
    for line in open(LOG, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
            total += 1
            if d.get("hit"):
                hit += 1
        except Exception:
            pass
    return {"total": total, "hit": hit, "hit_rate": round(hit / total, 3) if total else 0}


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--stats":
        print(json.dumps(stats(), ensure_ascii=False, indent=2))
    elif len(sys.argv) > 1:
        r = route_and_search(sys.argv[1])
        print(json.dumps({k: v for k, v in r.items() if k != "results"}, ensure_ascii=False, indent=2))
        print("\n--- 命中内容 ---")
        print(r.get("answer", "")[:1200])
    else:
        print("用法: python recall_router.py \"查询\"  |  --stats")
