# -*- coding: utf-8 -*-
"""memory_tools.py — 记忆自主检索（让凌麒自己决定注入什么）
================================================================
设计（对齐用户要求：不硬截断，它自己决定）：
  1. memory_index()  → 注入"记忆目录"（有什么、多大、什么时候），不注入全文
  2. recall(q)       → 按关键词跨文件检索，返回命中片段（它自己决定查什么）
  3. read 动作已有   → 它可以直接读任意文件全文
  ⇒ 系统只给"目录 + 索引"，内容由它按需取用，不再有 4000/1500 字符硬限制
"""
from config import (ROOT, AUTONOMY, SESSIONS, EXPERIENCE, NOTES,
                     MEMORY_MD, LESSONS, DIARY, LOG_DIR, CHROMA_DB,
                     SQLITE_DB, WING_KEYWORDS, SERVICES, MINE_INTERVAL,
                     CACHE_MAX, MEMPALACE_CLI, LLM_ENDPOINT, LLM_MODEL, LLM_KEY,
                     PORT_MEM_SERVICE, PORT_HUB)
import os, re, glob, datetime

BASE = os.path.dirname(os.path.abspath(__file__))
SESS = os.path.join(BASE, "sessions")


def _size_kb(p):
    try:
        return round(os.path.getsize(p) / 1024, 1)
    except Exception:
        return 0


def _mtime(p):
    try:
        return datetime.datetime.fromtimestamp(os.path.getmtime(p)).strftime("%m-%d %H:%M")
    except Exception:
        return "?"


def _first_line(p, n=60):
    try:
        with open(p, encoding="utf-8", errors="replace") as f:
            for _ in range(3):
                line = f.readline().strip()
                if line and not line.startswith("#"):
                    return line[:n]
        return ""
    except Exception:
        return ""


def memory_index(max_items=40):
    """记忆目录（只列清单+摘要，不注入内容）"""
    items = []

    # 1) 核心长期记忆
    for name, desc in [("MEMORY.md", "权威长期记忆（结论）"),
                       ("notes/lessons.md", "教训卡（已验证）"),
                       ("diary.md", "全部日记（流水，含情绪）"),
                       ("current_task.json", "当前任务"),
                       ("goals.json", "兴趣/好奇")]:
        p = os.path.join(BASE, name)
        if os.path.exists(p):
            items.append({"path": name, "kb": _size_kb(p), "mtime": _mtime(p),
                          "desc": desc, "hint": _first_line(p)})

    # 2) 会话
    cur = os.path.join(SESS, "current.jsonl")
    if os.path.exists(cur):
        try:
            n = sum(1 for _ in open(cur, encoding="utf-8", errors="replace"))
        except Exception:
            n = 0
        items.append({"path": "sessions/current.jsonl", "kb": _size_kb(cur),
                      "mtime": _mtime(cur), "desc": f"本次会话（{n} 轮）", "hint": ""})
    arch = sorted(glob.glob(os.path.join(SESS, "archive", "*.jsonl")), reverse=True)[:8]
    for f in arch:
        items.append({"path": "sessions/archive/" + os.path.basename(f),
                      "kb": _size_kb(f), "mtime": _mtime(f),
                      "desc": "历史会话", "hint": ""})

    # 3) notes
    notes = sorted(glob.glob(os.path.join(BASE, "notes", "*.md")), reverse=True)[:20]
    for f in notes:
        items.append({"path": "notes/" + os.path.basename(f), "kb": _size_kb(f),
                      "mtime": _mtime(f), "desc": "笔记", "hint": _first_line(f)})

    # 4) experience 最近的
    exps = sorted(glob.glob(os.path.join(BASE, "experience", "*.md")), reverse=True)[:10]
    for f in exps:
        items.append({"path": "experience/" + os.path.basename(f), "kb": _size_kb(f),
                      "mtime": _mtime(f), "desc": "经历轮次", "hint": ""})

    items = items[:max_items]
    lines = [f"【你的记忆资产目录（{len(items)} 项，这些内容不会自动注入——你想看哪个就用 recall 或 read）】"]
    for it in items:
        hint = f" | {it['hint']}" if it["hint"] else ""
        lines.append(f"  {it['path']:<52} {it['kb']:>7.1f}KB  {it['mtime']:<12} {it['desc']}{hint}")
    lines.append("  → 用法: recall {\"q\":\"关键词\"} 跨文件检索 / read {\"path\":\"MEMORY.md\"} 读全文")
    return "\n".join(lines)


DB = SQLITE_DB
NL = chr(10)


CHROMA = CHROMA_DB


def recall_chroma(q, limit=6, expand=True):
    """[Chroma 检索 2026-10-25] 12,418 抽屉 + 2,134 节点（closets）
    ① 直接命中 chroma:document
    ② 节点膨胀：同 wing/room 的其他记忆（联想激活）
    """
    import sqlite3
    kw = str(q or "").strip()
    if not kw:
        return "（recall_chroma 需要关键词）"
    try:
        con = sqlite3.connect("file:" + CHROMA + "?mode=ro", uri=True)
    except Exception as e:
        return "（Chroma 不可读: %s）" % e
    out = []
    rooms = set()
    try:
        rows = con.execute(
            "SELECT md.string_value, mr.string_value, mw.string_value, ms.string_value " +
            "FROM embedding_metadata md " +
            "LEFT JOIN embedding_metadata mr ON mr.id=md.id AND mr.key='room' " +
            "LEFT JOIN embedding_metadata mw ON mw.id=md.id AND mw.key='wing' " +
            "LEFT JOIN embedding_metadata ms ON ms.id=md.id AND ms.key='source_file' " +
            "WHERE md.key='chroma:document' AND md.string_value LIKE ? LIMIT " + str(max(1, min(int(limit), 30))),
            ("%" + kw + "%",)).fetchall()
        for doc, room, wing, sfile in rows:
            out.append("── [%s/%s] %s" % (wing or "?", room or "?", (sfile or "")[:50]) + NL +
                       "   " + str(doc)[:600].replace(NL, " "))
            if room:
                rooms.add((wing or "", room))
    except Exception as e:
        out.append("（查询异常: %s）" % str(e)[:100])
    # ② 节点膨胀：同 room 邻居
    if expand and rooms:
        for wing, room in list(rooms)[:2]:
            try:
                more = con.execute(
                    "SELECT md.string_value, ms.string_value FROM embedding_metadata md " +
                    "JOIN embedding_metadata mr ON mr.id=md.id AND mr.key='room' AND mr.string_value=? " +
                    "LEFT JOIN embedding_metadata ms ON ms.id=md.id AND ms.key='source_file' " +
                    "WHERE md.key='chroma:document' LIMIT 2", (room,)).fetchall()
                for doc, sfile in more:
                    block = ("── [膨胀/%s] %s" % (room, (sfile or "")[:50]) + NL +
                             "   " + str(doc)[:300].replace(NL, " "))
                    if block not in out:
                        out.append(block)
            except Exception:
                pass
    con.close()
    if not out:
        return "（Chroma 未命中「%s」）" % kw
    return "【Chroma 记忆宫殿「%s」：%d 条（含同房间膨胀）】" % (kw, len(out)) + NL + (NL + NL).join(out)


def recall_palace(q, limit=8, expand=True):
    """[节点膨胀 2026-10-25] 记忆宫殿检索：直接命中 → 沿 path/disclosure 膨胀出关联节点
    返回带关系标注的记忆链（命中 / 同路径 / 触发词匹配 / 时间邻近）
           """
    import sqlite3
    if not q or not str(q).strip():
        return "（recall_palace 需要关键词）"
    kw = str(q).strip()
    try:
        con = sqlite3.connect("file:" + DB + "?mode=ro", uri=True)
    except Exception as e:
        return "（记忆宫殿 DB 不可读: %s）" % e

    out = []
    seen = set()

    def add(rel, mid, content, path="", disc="", v=0.0, acc=0):
        if mid in seen or len(out) >= limit:
            return
        seen.add(mid)
        head = content.strip().split(chr(10))[0][:110]
        body = content.strip()[:700]
        tag = "[%s]" % rel
        extra = (" path=%s" % path) if path else ""
        out.append("── %s id=%s v=%.2f acc=%d%s" % (tag, mid, v, acc, extra) + NL +
                   "   " + body.replace(chr(10), NL + "   "))

    # ① 直接命中（content 含关键词）
    try:
        _lim = max(1, min(int(limit), 50))
        for r in con.execute(
            "SELECT id, content, vitality_score, access_count FROM memories "
            "WHERE deprecated=0 AND content LIKE ? ORDER BY vitality_score DESC, access_count DESC LIMIT " + str(_lim),
            ("%" + kw + "%",)):
            add("命中", r[0], r[1], v=float(r[2] or 0), acc=int(r[3] or 0))
    except Exception:
        pass

    # ② 触发词命中（paths.disclosure 含关键词 = 这个场景该想起这条）
    hits_paths = []
    try:
        _lim2 = max(1, min(int(limit), 50))
        hits_paths = con.execute(
            "SELECT p.path, p.memory_id, p.disclosure, m.content, m.vitality_score, m.access_count "
            "FROM paths p JOIN memories m ON m.id=p.memory_id "
            "WHERE m.deprecated=0 AND (p.disclosure LIKE ? OR p.path LIKE ?) "
            "ORDER BY p.priority LIMIT " + str(_lim2),
            ("%" + kw + "%", "%" + kw + "%")).fetchall()
        for r in hits_paths:
            add("触发", r[1], r[3], path=r[0], disc=(r[2] or "")[:40], v=float(r[4] or 0), acc=int(r[5] or 0))
    except Exception:
        pass

    # ③ 节点膨胀：沿命中的 path 前缀扩展同簇邻居（记忆连锁）
    if expand and out:
        prefixes = set()
        for r in hits_paths:
            p = (r[0] or "").split("_")[0]
            if p:
                prefixes.add(p + "_")
        for pre in list(prefixes)[:3]:
            try:
                for r in con.execute(
                    "SELECT p.path, p.memory_id, m.content, m.vitality_score, m.access_count "
                    "FROM paths p JOIN memories m ON m.id=p.memory_id "
                    "WHERE m.deprecated=0 AND p.path LIKE ? ORDER BY p.priority LIMIT 3",
                    (pre + "%",)):
                    add("膨胀", r[1], r[2], path=r[0], v=float(r[3] or 0), acc=int(r[4] or 0))
            except Exception:
                pass
    con.close()
    if not out:
        return "（记忆宫殿中未找到「%s」——可换关键词或先 mine 入库）" % kw
    return "【记忆宫殿检索「%s」：%d 条（含膨胀关联）】" % (kw, len(out)) + NL + (NL + NL).join(out)


def recall(q, limit=6000, context_lines=2, max_files=30):
    """按关键词跨文件检索记忆，返回命中片段（片段总数受 limit 字符约束）"""
    if not q or not q.strip():
        return "（recall 需要关键词）"
    kw = q.strip()
    # 关键词分词（支持空格多词 OR / 单关键词）
    terms = [t for t in re.split(r"[\s,，]+", kw) if t]
    if not terms:
        return "（关键词为空）"

    targets = []
    for pat in ["MEMORY.md", "notes/lessons.md", "diary.md", "current_task.json", "goals.json"]:
        p = os.path.join(BASE, pat)
        if os.path.exists(p):
            targets.append(p)
    targets += sorted(glob.glob(os.path.join(SESS, "current.jsonl")))
    targets += sorted(glob.glob(os.path.join(SESS, "archive", "*.jsonl")), reverse=True)[:10]
    targets += sorted(glob.glob(os.path.join(BASE, "notes", "*.md")), reverse=True)[:20]
    targets += sorted(glob.glob(os.path.join(BASE, "experience", "*.md")), reverse=True)[:60]
    targets = targets[:max_files + 100]

    hits = []
    total = 0
    for p in targets:
        try:
            with open(p, encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
        except Exception:
            continue
        rel = os.path.relpath(p, BASE).replace("\\", "/")
        for i, line in enumerate(lines):
            low = line.lower()
            if not any(t.lower() in low for t in terms):
                continue
            a = max(0, i - context_lines)
            b = min(len(lines), i + context_lines + 1)
            snippet = "".join(lines[a:b]).strip()
            if len(snippet) > 800:
                snippet = snippet[:800] + "…"
            block = f"── {rel}:{i+1}\n{snippet}\n"
            if total + len(block) > limit:
                hits.append(f"\n（已达检索上限 {limit} 字符，共命中更多；请缩小关键词）")
                return "".join(hits)
            hits.append(block)
            total += len(block)
    if not hits:
        return f"（在 {len(targets)} 个文件中未找到「{kw}」，可换关键词或直接 read 已知文件）"
    return f"【recall「{kw}」命中 {len(hits)} 处】\n" + "".join(hits)


if __name__ == "__main__":
    import sys, json
    cmd = sys.argv[1] if len(sys.argv) > 1 else "index"
    if cmd == "index":
        print(memory_index())
    elif cmd == "recall":
        print(recall(sys.argv[2] if len(sys.argv) > 2 else ""))
