# -*- coding: utf-8 -*-
"""autostart_all.py — 联携自启动器（一个入口拉起全部常驻服务）
================================================================
用户需求（2026-10-25）：
  1. 常驻服务系统级自启（不靠手动）
  2. 联携启动（按依赖顺序 + 各自健康检查）

服务清单（按启动顺序）：
  1. compress-proxy   8500 → 8400  请求瘦身代理（node，无窗口）
  2. mem_service      8950         记忆检索常驻服务（python，无窗口）
  3. alive.py                    凌麒本体（由 AutonomyAlive 任务管，这里只做状态检查）

启动方式：HKCU\...\Run 指向本脚本（登录即跑）
        schtasks ONLOGON 需要管理员，HKCU Run 不需要（实测被拒过）

用法：
  pythonw autostart_all.py           # 启动全部（无窗口）
  python   autostart_all.py --status # 只看状态
  python   autostart_all.py --restart # 全停再全起
"""
from config import (ROOT, AUTONOMY, SESSIONS, EXPERIENCE, NOTES,
                     MEMORY_MD, LESSONS, DIARY, LOG_DIR, CHROMA_DB,
                     SQLITE_DB, WING_KEYWORDS, SERVICES, MINE_INTERVAL,
                     CACHE_MAX, MEMPALACE_CLI, LLM_ENDPOINT, LLM_MODEL, LLM_KEY,
                     PORT_MEM_SERVICE, PORT_HUB)
import os
import sys
import time
import socket
import subprocess

# ── 路径配置 ──
VENV_PYW = sys.executable
NODE = "node"
CREATE_NO_WINDOW = 0x08000000

SERVICES = [
    {
        "name": "compress-proxy",
        "port": 8500,
        "cmd": [NODE, os.path.join(ROOT, "compress-proxy.mjs")],
        "cwd": ROOT,
        "desc": "请求瘦身代理 8500→8400",
    },
    {
        "name": "mem_service",
        "port": 8950,
        "cmd": [VENV_PYW, os.path.join(AUTONOMY, "mem_service.py")],
        "cwd": AUTONOMY,
        "desc": "记忆检索常驻（8950）",
    },
]

LOG_DIR = LOG_DIR
os.makedirs(LOG_DIR, exist_ok=True)
LOG = os.path.join(LOG_DIR, "autostart_all.log")


def log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + chr(10))
    except Exception:
        pass


def port_ok(port, timeout=2):
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


def find_procs(name):
    """用 venv python 找进程（系统 python 的 psutil 常被更新搞坏）"""
    try:
        code = (
            "import psutil,sys;"
            "out=[];"
            "for p in psutil.process_iter(['pid','name','cmdline']):\n"
            "    try:\n"
            "        cl=' '.join(p.info.get('cmdline') or [])\n"
            "        if '%s' in cl: out.append((p.info['pid'],p.info.get('name') or ''))\n"
            "    except Exception: pass\n"
            "print(out)"
        ) % name
        r = subprocess.run([VENV_PYW, "-c", code], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return eval(r.stdout.strip())
    except Exception:
        pass
    return []


def stop_service(name):
    procs = find_procs(name)
    n = 0
    for pid, nm in procs:
        try:
            subprocess.run([VENV_PYW, "-c",
                            "import psutil;psutil.Process(%d).kill()" % pid],
                           capture_output=True, timeout=15)
            n += 1
        except Exception:
            pass
    return n


def start_service(svc):
    if port_ok(svc["port"]):
        log("  %-16s 已在跑（%d）" % (svc["name"], svc["port"]))
        return True
    log("  %-16s 启动中…" % svc["name"])
    out = open(os.path.join(LOG_DIR, svc["name"] + ".log"), "a", encoding="utf-8")
    try:
        subprocess.Popen(svc["cmd"], cwd=svc["cwd"], stdout=out, stderr=out,
                         creationflags=CREATE_NO_WINDOW, close_fds=True)
    except Exception as e:
        log("  %-16s 启动失败: %s" % (svc["name"], e))
        return False
    for _ in range(10):
        time.sleep(1)
        if port_ok(svc["port"]):
            log("  %-16s ✓ 就绪（%d）" % (svc["name"], svc["port"]))
            return True
    log("  %-16s ⚠ 10 秒未响应" % svc["name"])
    return False


def status():
    log("=== 状态 ===")
    for svc in SERVICES:
        ok = port_ok(svc["port"])
        procs = find_procs(svc["name"])
        log("  %-16s %s  进程=%d  %s" % (svc["name"], "✓" if ok else "✗", len(procs), svc["desc"]))
    # 凌麒
    hb = os.path.join(AUTONOMY, "alive_state.json")
    if os.path.exists(hb):
        age = time.time() - os.path.getmtime(hb)
        log("  %-16s %s  心跳 %.0f 秒前" % ("alive(凌麒)", "✓" if age < 600 else "⚠", age))
    # 黑窗
    cmds = find_procs("cmd.exe /d /s /c")
    log("  cmd 黑窗: %d 个（0 = 无）" % len(cmds))


def main():
    args = sys.argv[1:]
    log("=== autostart_all 开始 ===")
    if "--status" in args:
        status()
        return
    if "--restart" in args:
        for svc in SERVICES:
            n = stop_service(svc["name"])
            log("  %-16s 停掉 %d 个" % (svc["name"], n))
        time.sleep(3)
    ok = 0
    for svc in SERVICES:
        if start_service(svc):
            ok += 1
    log("=== 完成 %d/%d，最后状态 ===" % (ok, len(SERVICES)))
    status()


if __name__ == "__main__":
    main()
