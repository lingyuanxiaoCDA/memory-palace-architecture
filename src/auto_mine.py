# -*- coding: utf-8 -*-
"""auto_mine.py — 自动把结论文件 mine 进记忆宫殿（增量，幂等）
================================================================
用户需求：每次对话产生的数据自动存入记忆宫殿
现实：WorkBuddy 对话正文不在本地（云端），但**结论文件在本地**
方案：定时 mine 这些高价值目录（结论 > 对话原文）

目录优先级（均相对于 config.ROOT）：
  1. knowledge/      — 结论卡片（策略溯源/审计/状态表）
  2. memory/         — 每日工作日志 + MEMORY.md
  3. deliverables/   — 交付文档
  4. sessions/       — AI 会话（autonomy/sessions）
  5. experience/     — 轮次经历（autonomy/experience）

用法：
  python auto_mine.py            # mine 全部
  python auto_mine.py --dry-run  # 只看工作量
  python auto_mine.py --only knowledge
"""
from config import (ROOT, AUTONOMY, SESSIONS, EXPERIENCE, NOTES,
                     MEMORY_MD, LESSONS, DIARY, LOG_DIR, CHROMA_DB,
                     SQLITE_DB, WING_KEYWORDS, SERVICES, MINE_INTERVAL,
                     CACHE_MAX, MEMPALACE_CLI, LLM_ENDPOINT, LLM_MODEL, LLM_KEY,
                     PORT_MEM_SERVICE, PORT_HUB)
import subprocess, sys, os, time, json

PALACE = os.path.dirname(CHROMA_DB)
MP = MEMPALACE_CLI
LOG = os.path.join(LOG_DIR, "auto_mine.log")

TARGETS = [
    ("knowledge",   os.path.join(ROOT, "knowledge")),
    ("memory",      os.path.join(ROOT, "memory")),
    ("deliverables", os.path.join(ROOT, "deliverables")),
    ("sessions",    os.path.join(AUTONOMY, "sessions")),
    ("experience",  os.path.join(AUTONOMY, "experience")),
]


def log(msg):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + chr(10))


def mine(name, path, dry=False):
    if not os.path.isdir(path):
        log(f"{name}: 目录不存在，跳过")
        return False
    cmd = [MP, "--palace", PALACE, "mine", path, "--mode", "projects", "--direct"]
    if dry:
        cmd.append("--dry-run")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600)
    dur = time.time() - t0
    tail = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-3:]
    log(f"{name}: {'dry' if dry else 'done'} {dur:.0f}s | " + " / ".join(tail)[:200])
    return r.returncode == 0


def main():
    args = sys.argv[1:]
    dry = "--dry-run" in args
    only = None
    if "--only" in args:
        i = args.index("--only")
        if i + 1 < len(args):
            only = args[i + 1]
    t0 = time.time()
    ok = 0
    for name, path in TARGETS:
        if only and name != only:
            continue
        if mine(name, path, dry):
            ok += 1
    log(f"=== 完成 {ok} 个目录，总耗时 {time.time()-t0:.0f}s ===")


if __name__ == "__main__":
    main()
