# -*- coding: utf-8 -*-
"""mem_service.py — 记忆常驻服务（只读检索 + 内部定时 mine）
================================================================
架构决策（2026-10-25，用户指正"定时任务重启会掉"）：
  · mempalace MCP  = 唯一 writer（常驻，WorkBuddy 管理）→ 负责 mine/写
  · mem_service    = 只读服务（常驻，本文件）→ 负责快速检索 + 缓存 + 定时触发 mine
  · alive.py       = 凌麒（常驻）
  三者都由 ONLOGON 拉起，重启电脑后自动恢复，不依赖定时任务。

为什么不用 mempalace daemon：
  daemon 要求 writer 独占，与 MCP 冲突（实测 DaemonError: another writer owns ...）
  只读服务用 SQLite WAL 可多进程并行，不冲突。

接口（HTTP 127.0.0.1:8950）：
  GET  /health          → {"ok":true, "uptime":..., "cache":...}
  POST /recall          {"need":"...", "limit":5} → {wings, results, hit, ms}
  GET  /stats            → 检索统计 + 日志条数
  POST /mine            {"only":"knowledge"} → 触发一次 mine（后台线程）

内部定时：每 MINE_INTERVAL 秒自动 mine 一次（默认 4 小时）

启动：
  pythonw mem_service.py          # 后台常驻
  python  mem_service.py --once   # 前台跑一次自检后退出
"""
import os, sys, json, time, sqlite3, threading, re
from http.server import HTTPServer, BaseHTTPRequestHandler
try:
    from config import (LOG_DIR, CHROMA_DB, SQLITE_DB, AUTONOMY, ROOT,
                        WING_KEYWORDS, MEMPALACE_CLI)
except Exception:                                   # 未装 config 时用默认值
    LOG_DIR = os.path.join(os.path.expanduser("~"), ".memory-palace", "tmp")
    CHROMA_DB = os.path.join(os.path.expanduser("~"), ".memory-palace", "palace", "chroma.sqlite3")
    SQLITE_DB = os.path.join(os.path.expanduser("~"), ".memory-palace", "agent_memory.db")
    AUTONOMY = os.path.join(os.path.expanduser("~"), ".memory-palace", "autonomy")
    ROOT = os.path.join(os.path.expanduser("~"), ".memory-palace")
    WING_KEYWORDS = {}
    MEMPALACE_CLI = "mempalace"


BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PALACE = os.path.dirname(CHROMA_DB)
CHROMA = os.path.join(PALACE, "chroma.sqlite3")
PORT = 8950
MINE_INTERVAL = 4 * 3600      # 4 小时
LOG = os.path.join(LOG_DIR, "mem_service.log")

# ── 内存缓存（避免重复查 SQLite）──
_cache = {}
_cache_order = []
CACHE_MAX = 200
_lock = threading.Lock()


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}" + chr(10))
    except Exception:
        pass


def _cache_get(k):
    with _lock:
        return _cache.get(k)


def _cache_put(k, v):
    with _lock:
        if k not in _cache:
            _cache_order.append(k)
        _cache[k] = v
        while len(_cache_order) > CACHE_MAX:
            old = _cache_order.pop(0)
            _cache.pop(old, None)


# ── 懒加载 recall_router（复用其路由与分词逻辑）──
_router = None


def router():
    global _router
    if _router is None:
        import recall_router
        _router = recall_router
    return _router


def do_recall(need, limit=5):
    key = (need, limit)
    hit = _cache_get(key)
    if hit is not None:
        return dict(hit, cached=True)
    r = router().route_and_search(need, limit=limit, log=True)
    slim = {k: v for k, v in r.items() if k != "results"}
    slim["top"] = [{"wing": x.get("wing"), "src": os.path.basename(x.get("source") or ""),
                    "score": x.get("score"), "text": x.get("text", "")[:300]} for x in r.get("results", [])]
    _cache_put(key, slim)
    return slim


# ── 内部定时 mine（替代 schtasks 定时任务）──
def mine_loop():
    time.sleep(60)   # 启动后先等 1 分钟
    while True:
        try:
            import auto_mine
            ok = 0
            for name, path in auto_mine.TARGETS:
                if auto_mine.mine(name, path, dry=False):
                    ok += 1
            log(f"定时 mine 完成: {ok}/{len(auto_mine.TARGETS)}")
        except Exception as e:
            log(f"定时 mine 异常: {type(e).__name__}: {e}")
        time.sleep(MINE_INTERVAL)


# ── 连带训练循环（用户 2026-10-25："日志攒够再训太慢，不如做连带"）──
# 不等攒够：每 10 分钟检查，新增 ≥3 条日志 或 距上次训练 >6 小时 → 自动重训
TRAIN_CHECK_EVERY = 600          # 10 分钟检查一次
TRAIN_MIN_NEW = 3                # 新增几条触发
TRAIN_MAX_IDLE = 6 * 3600        # 6 小时没训过也训一次（保证模型不过期）


def _count_logs():
    try:
        import recall_router
        return recall_router.stats().get("total", 0)
    except Exception:
        return 0


def training_loop():
    """连带：检索 → 日志 → 自动重训 → 下次检索自动用新模型（模型文件 mtime 变化即热加载）"""
    time.sleep(120)              # 启动 2 分钟后首次训练
    last_n = _count_logs()
    last_train = time.time()
    while True:
        time.sleep(TRAIN_CHECK_EVERY)
        try:
            import train_router
            n = _count_logs()
            new = n - last_n
            idle = time.time() - last_train
            if new >= TRAIN_MIN_NEW or idle >= TRAIN_MAX_IDLE:
                r = train_router.train()
                if r.get("ok"):
                    log(f"连带训练完成: 样本 {r.get('n_total')}（真实 {r.get('n_real')}）"
                        f" {r.get('train_ms')}ms | 触发: 新增{new}条/闲置{int(idle/3600)}h")
                    last_n = n
                    last_train = time.time()
        except Exception as e:
            log(f"连带训练异常: {type(e).__name__}: {e}")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"ok": True, "uptime_s": round(time.time() - START),
                             "cache_size": len(_cache), "port": PORT,
                             "palace_ok": os.path.exists(CHROMA)})
        elif self.path.startswith("/stats"):
            try:
                st = router().stats()
            except Exception as e:
                st = {"error": str(e)[:100]}
            self._send(200, {"recall_stats": st, "cache_size": len(_cache)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if self.path.startswith("/recall"):
            need = str(body.get("need") or body.get("q") or "")
            lim = int(body.get("limit") or 5)
            t0 = time.time()
            r = do_recall(need, lim)
            r["ms_total"] = round((time.time() - t0) * 1000, 1)
            self._send(200, r)
        elif self.path.startswith("/mine"):
            only = body.get("only")
            def _run():
                try:
                    import auto_mine
                    for name, path in auto_mine.TARGETS:
                        if only and name != only:
                            continue
                        auto_mine.mine(name, path)
                except Exception as e:
                    log(f"手动 mine 异常: {e}")
            threading.Thread(target=_run, daemon=True).start()
            self._send(200, {"started": True, "only": only})
        else:
            self._send(404, {"error": "not found"})


START = time.time()


def main():
    once = "--once" in sys.argv
    log(f"=== mem_service 启动 (port={PORT}, mine间隔={MINE_INTERVAL}s) ===")
    if once:
        r = do_recall("V37 验证 结论", 3)
        print(json.dumps(r, ensure_ascii=False, indent=2)[:800])
        return
    threading.Thread(target=mine_loop, daemon=True).start()
    threading.Thread(target=training_loop, daemon=True).start()   # 连带训练
    srv = HTTPServer(("127.0.0.1", PORT), Handler)
    log(f"监听 127.0.0.1:{PORT}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        log("手动停止")


if __name__ == "__main__":
    main()
