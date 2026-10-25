# -*- coding: utf-8 -*-
"""session.py — 凌麒的会话结构（对齐 WorkBuddy 模型）
================================================================
核心概念（WorkBuddy 同构）：
  1. 会话 = 一次连续工作的完整对话历史（亲历），新会话 = 清空上下文但保留长期记忆
  2. 长期记忆 MEMORY.md / lessons.md = 跨会话强制注入（不截断）
  3. 会话归档时提炼 3 条结论进 MEMORY.md（把"亲历"沉淀成"长效"）

文件布局：
  autonomy/sessions/current.jsonl     当前会话（每行一轮：{role, content, ts, action})
  autonomy/sessions/archive/YYYYMMDD_HHMM_<task>.jsonl   归档会话
  autonomy/sessions/summary.jsonl     每次归档的结论摘要（供 MEMORY 提炼）

用法：
  from session import append_turn, current_turns, rotate, session_info
"""
import json, os, glob, datetime, re

BASE = os.path.dirname(os.path.abspath(__file__))
SESS_DIR = os.path.join(BASE, "sessions")
ARCHIVE = os.path.join(SESS_DIR, "archive")
CUR = os.path.join(SESS_DIR, "current.jsonl")
SUMMARY = os.path.join(SESS_DIR, "summary.jsonl")


def _ensure():
    os.makedirs(ARCHIVE, exist_ok=True)


def append_turn(role, content, **meta):
    """追加一轮对话（role: user/assistant/tool）"""
    _ensure()
    rec = {"ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "role": role, "content": (content or "")[:20000]}
    rec.update(meta)
    try:
        with open(CUR, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def current_turns(limit=None, max_chars=None):
    """读当前会话的完整轮次（默认全部；可限轮数/总字符）"""
    if not os.path.exists(CUR):
        return []
    out = []
    try:
        with open(CUR, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    if limit:
        out = out[-limit:]
    if max_chars:
        # 从最新往前累加，超预算就截断（保留最近的）
        total = 0
        keep = []
        for r in reversed(out):
            c = len(r.get("content", ""))
            if total + c > max_chars:
                break
            keep.append(r)
            total += c
        out = list(reversed(keep))
    return out


def format_turns(turns, max_chars=120000):
    """把轮次格式化成可注入文本"""
    if not turns:
        return "（本次会话刚开始，还没有对话记录）"
    lines = []
    total = 0
    for r in turns:
        role = r.get("role", "?")
        ts = r.get("ts", "")
        act = r.get("action", "")
        head = {"user": "【他】", "assistant": "【我】", "tool": "【结果】"}.get(role, f"【{role}】")
        tag = f"({act})" if act else ""
        block = f"{head}{tag} {ts}\n{r.get('content','')}\n"
        if total + len(block) > max_chars:
            break
        lines.append(block)
        total += len(block)
    return "\n".join(lines)


def session_info():
    """当前会话基本信息"""
    turns = current_turns()
    if not turns:
        return {"turns": 0, "started": None, "chars": 0, "file": CUR}
    return {"turns": len(turns), "started": turns[0].get("ts"),
            "chars": sum(len(t.get("content", "")) for t in turns), "file": CUR}


def rotate(task="", conclusions=None):
    """新建会话：归档当前会话 → 结论写进 summary + MEMORY.md → 开新会话
    conclusions: list[str]，3 条以内结论（由调用方提炼或人工提供）
    """
    _ensure()
    info = session_info()
    if info["turns"] == 0:
        return {"rotated": False, "reason": "当前会话为空"}
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (task or "session"))[:40]
    dst = os.path.join(ARCHIVE, f"{stamp}_{safe}.jsonl")
    try:
        os.replace(CUR, dst)
    except Exception as e:
        return {"rotated": False, "reason": f"归档失败: {e}"}

    # 结论摘要
    rec = {"ts": stamp, "task": task, "turns": info["turns"],
           "chars": info["chars"], "archive": os.path.basename(dst),
           "conclusions": conclusions or []}
    with open(SUMMARY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # 结论写进 MEMORY.md（长期记忆）
    if conclusions:
        mp = os.path.join(BASE, "MEMORY.md")
        try:
            with open(mp, "a", encoding="utf-8") as f:
                f.write(f"\n## {stamp} 会话结论（{task or '未命名'}）\n")
                for c in conclusions[:5]:
                    f.write(f"- {c}\n")
        except Exception:
            pass
    return {"rotated": True, "archive": dst, "turns": info["turns"],
            "conclusions": len(conclusions or [])}


def list_archives(limit=10):
    """列出最近归档会话"""
    out = []
    for f in sorted(glob.glob(os.path.join(ARCHIVE, "*.jsonl")), reverse=True)[:limit]:
        try:
            n = sum(1 for _ in open(f, encoding="utf-8", errors="replace"))
        except Exception:
            n = 0
        out.append({"file": os.path.basename(f), "turns": n,
                    "size_kb": round(os.path.getsize(f) / 1024, 1)})
    return out


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "info"
    if cmd == "info":
        print(json.dumps(session_info(), ensure_ascii=False, indent=2))
    elif cmd == "archives":
        print(json.dumps(list_archives(), ensure_ascii=False, indent=2))
    elif cmd == "rotate":
        task = sys.argv[2] if len(sys.argv) > 2 else ""
        print(json.dumps(rotate(task=task), ensure_ascii=False, indent=2))
