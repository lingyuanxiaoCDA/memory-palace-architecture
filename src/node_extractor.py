# -*- coding: utf-8 -*-
"""node_extractor.py — 档案 → 节点 提取器（白纸原则 / 不修剪 / 联想激活基础）
================================================================
用户架构（2026-10-25）：
  · 原始档案（memories/chunks/diary/sessions/experience）**永不删，保完整性**
  · 档案不断被提取 → 产出节点（gists 摘要 / tags 概念 / paths 触发条件）
  · 节点之间形成边 → 联想式激活（一个节点激活一片）
  · **不修剪**：不做 DECAY/PRUNE（当初 3G→27G 的修剪是一次性工程，现在不需要）

本脚本职责（单向：档案 → 节点，绝不改档案）：
  1. 扫描 experience/*.md + sessions/archive/*.jsonl 里**尚未提取**的档案
  2. 提炼：标题 → 节点 path；关键词 → tag；摘要 → gist；触发条件 → disclosure
  3. 写入 memory_gists / memory_tags / paths（幂等，重复跑不重复写）
  4. 输出提取报告

用法:
  python node_extractor.py            # 提取全部未处理的
  python node_extractor.py --limit 20 # 只处理最近 20 个
  python node_extractor.py --stats    # 只看节点统计
"""
from config import (ROOT, AUTONOMY, SESSIONS, EXPERIENCE, NOTES,
                     MEMORY_MD, LESSONS, DIARY, LOG_DIR, CHROMA_DB,
                     SQLITE_DB, WING_KEYWORDS, SERVICES, MINE_INTERVAL,
                     CACHE_MAX, MEMPALACE_CLI, LLM_ENDPOINT, LLM_MODEL, LLM_KEY,
                     PORT_MEM_SERVICE, PORT_HUB)
import os, re, json, sqlite3, hashlib, datetime, sys, argparse

BASE = os.path.dirname(os.path.abspath(__file__))
DB = SQLITE_DB
EXP = os.path.join(BASE, "experience")
SESS_ARCH = os.path.join(BASE, "sessions", "archive")
NOTE = os.path.join(BASE, "notes")

# 中文/英文关键词提取（无第三方依赖）
STOP = set("""的 了 是 在 我 有 和 就 不 人 都 一 一个 上 也 很 到 说 要 去 你 会 着 没有 看 好 自 己 这 那 它 他 她
the a an is are was were be been to of and or in on at for with by this that it as from""".split())
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{2,}|[\u4e00-\u9fff]{2,6}")


def _connect():
    con = sqlite3.connect(DB, timeout=20)
    con.execute("PRAGMA journal_mode=WAL")
    return con


def _tokens(text, top=8):
    cnt = {}
    for m in TOKEN_RE.finditer(text or ""):
        w = m.group(0)
        if w.lower() in STOP or len(w) < 2:
            continue
        cnt[w] = cnt.get(w, 0) + 1
    return [w for w, _ in sorted(cnt.items(), key=lambda x: -x[1])[:top]]


def _h(s):
    return hashlib.sha1((s or "").encode("utf-8", errors="replace")).hexdigest()[:16]


def _already(con, src):
    """幂等：paths 里已有该源标识就跳过"""
    r = con.execute("SELECT 1 FROM paths WHERE path=? LIMIT 1", (src,)).fetchone()
    return bool(r)


def extract_file(con, path, kind="experience"):
    """从一个档案文件提取节点，返回 (gist_written, tags_written, path_written)"""
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return 0, 0, 0
    if len(text.strip()) < 40:
        return 0, 0, 0

    fname = os.path.basename(path)
    src = (kind + ":" + fname)[:120]
    if _already(con, src):
        return 0, 0, 0

    # 标题：第一个 heading 或首行
    title = ""
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("#"):
            title = s.lstrip("# ").strip()
            if title:
                break
        elif s and not title:
            title = s[:80]
    title = (title or fname)[:120]

    # 摘要：正文前 400 字（去 markdown 符号）
    body = re.sub(r"[#*`>\-]{1,}", " ", text)
    body = re.sub(r"\s+", " ", body).strip()
    gist = body[:400]

    # 关键词 → tag
    tags = _tokens(text, top=8)

    # 触发条件（disclosure）：标题 + 关键词 → "当涉及X、Y时"
    disclosure = ("当涉及 " + "、".join(tags[:5]) + " 时") if tags else ("当涉及 " + title[:40] + " 时")

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    wrote = [0, 0, 0]

    # ① memory_gists（摘要节点）
    try:
        con.execute(
            "INSERT INTO memory_gists (memory_id, gist_text, source_content_hash, gist_method, "
            "quality_score, created_at, derivation_method, confidence, review_state) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (fname, gist, _h(text), "rule_v1", 0.6, now, "node_extractor", 0.6, "auto"))
        wrote[0] = 1
    except Exception:
        pass

    # ② memory_tags（概念节点）
    for t in tags:
        try:
            con.execute(
                "INSERT INTO memory_tags (memory_id, tag_type, tag_value, confidence, created_at) "
                "VALUES (?,?,?,?,?)", (fname, "topic", t, 0.6, now))
            wrote[1] += 1
        except Exception:
            pass

    # ③ paths（触发条件 → 可联想激活的边）
    try:
        con.execute(
            "INSERT INTO paths (domain, path, memory_id, created_at, priority, disclosure) "
            "VALUES (?,?,?,?,?,?)",
            ("node", src, fname, now, 2, disclosure[:200]))
        wrote[2] = 1
    except Exception:
        pass

    return tuple(wrote)


def stats():
    con = _connect()
    out = {}
    for t in ["memories", "memory_chunks", "memory_gists", "memory_tags", "paths", "memory_summaries"]:
        try:
            out[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        except Exception:
            out[t] = -1
    try:
        out["node_domain_paths"] = con.execute(
            "SELECT COUNT(*) FROM paths WHERE domain='node'").fetchone()[0]
    except Exception:
        out["node_domain_paths"] = -1
    con.close()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stats", action="store_true")
    args = ap.parse_args()

    before = stats()
    print("=== 提取前 ===")
    for k, v in before.items():
        print(f"  {k}: {v}")

    if args.stats:
        return

    files = []
    for d, kind in [(EXP, "experience"), (NOTE, "notes"), (SESS_ARCH, "session")]:
        if not os.path.isdir(d):
            continue
        for f in sorted(os.listdir(d), reverse=True):
            if not (f.endswith(".md") or f.endswith(".jsonl")):
                continue
            files.append((os.path.join(d, f), kind))
    if args.limit:
        files = files[:args.limit]

    con = _connect()
    tot = [0, 0, 0]
    done = 0
    for p, kind in files:
        g, t, pa = extract_file(con, p, kind)
        if g or t or pa:
            tot[0] += g; tot[1] += t; tot[2] += pa; done += 1
    con.commit()
    con.close()

    print(f"\n=== 提取完成 ===")
    print(f"  处理档案: {done}/{len(files)}")
    print(f"  新增 gists: {tot[0]} | tags: {tot[1]} | paths: {tot[2]}")
    after = stats()
    print(f"\n=== 提取后 ===")
    for k, v in after.items():
        delta = v - before[k]
        print(f"  {k}: {v}" + (f"  (+{delta})" if delta > 0 else ""))


if __name__ == "__main__":
    main()
