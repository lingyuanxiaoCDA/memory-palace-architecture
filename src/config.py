# -*- coding: utf-8 -*-
"""config.py — 统一配置（开源版）
================================================================
所有路径/端口集中在这里，适配你的环境只需改这一个文件。
也支持环境变量覆盖（优先级：环境变量 > 本文件默认值）。
"""
import os

# ── 根目录 ──
ROOT = os.environ.get("MP_ROOT", os.path.expanduser("~/memory-palace"))

# ── 存储库 ──
# Chroma（mempalace 主库）：drawers + closets
CHROMA_DB = os.environ.get(
    "MP_CHROMA", os.path.join(ROOT, "palace", "chroma.sqlite3"))
# SQLite（辅助库）：memories + paths + gists
SQLITE_DB = os.environ.get(
    "MP_SQLITE", os.path.join(os.path.expanduser("~"), "memory_palace", "agent_memory.db"))

# ── 工作目录（凌麒的自治目录）──
AUTONOMY = os.environ.get("MP_AUTONOMY", os.path.join(ROOT, "autonomy"))
SESSIONS = os.path.join(AUTONOMY, "sessions")
EXPERIENCE = os.path.join(AUTONOMY, "experience")
NOTES = os.path.join(AUTONOMY, "notes")
MEMORY_MD = os.path.join(AUTONOMY, "MEMORY.md")
LESSONS = os.path.join(NOTES, "lessons.md")
DIARY = os.path.join(AUTONOMY, "diary.md")
LOG_DIR = os.environ.get("MP_LOG_DIR", os.path.join(ROOT, "_tmp"))

# ── 服务端口 ──
PORT_MEM_SERVICE = int(os.environ.get("MP_PORT_MEM", "8950"))     # 记忆检索常驻
PORT_COMPRESS_PROXY = int(os.environ.get("MP_PORT_COMPRESS", "8500"))  # 请求瘦身代理
PORT_LLM_POOL = int(os.environ.get("MP_PORT_LLM", "8400"))        # 模型别名反代
PORT_LOCAL_LLM = int(os.environ.get("MP_PORT_LOCAL_LLM", "1234"))  # 本地模型
PORT_HUB = int(os.environ.get("MP_PORT_HUB", "8942"))             # 中枢

# ── mempalace CLI ──
# 安装：pip install mempalace 或 uv tool install mempalace
MEMPALACE_CLI = os.environ.get(
    "MP_MEMPALACE_CLI", "mempalace")   # 找不到就用全路径，如 ~/AppData/Roaming/uv/tools/mempalace/Scripts/mempalace.exe

# ── LLM（节点生成/LLM 层用）──
LLM_ENDPOINT = os.environ.get("MP_LLM_ENDPOINT", "http://127.0.0.1:%d/v1" % PORT_LLM_POOL)
LLM_MODEL = os.environ.get("MP_LLM_MODEL", "g2-vice")
LLM_KEY = os.environ.get("MP_LLM_KEY", "")

# ── 检索参数 ──
MINE_INTERVAL = int(os.environ.get("MP_MINE_INTERVAL", str(4 * 3600)))  # 自动入库间隔（秒）
CACHE_MAX = int(os.environ.get("MP_CACHE_MAX", "200"))                  # 内存缓存条数

# ── 19 个 Wing 路由关键词（recall_router 用，可自行扩充）──
WING_KEYWORDS = {
    "策略方法论": ["策略", "r18", "回测", "夏普", "回撤", "pf", "oos", "胜率", "盈亏比", "参数", "闸门", "反过拟合"],
    "ai_trading": ["实盘", "下单", "okx", "仓位", "杠杆", "止损", "止盈", "爆仓", "保证金", "交易所"],
    "量化研究": ["因子", "特征", "样本", "相关性", "spearman", "ic", "alpha", "信号", "k线", "指标"],
    "quant-r18": ["r18", "双腿", "5m", "30m", "解锁", "触障", "sigma", "宽障碍"],
    "autonomy": ["凌麒", "自主", "心跳", "决策", "漂移", "审计", "会话", "节点"],
    "工作记忆": ["工作日志", "任务", "进度", "待办", "交接"],
    "knowledge": ["结论", "审计", "配置卡", "溯源", "状态表", "铁律"],
    "学习中心": ["速查", "教程", "笔记", "学习方法", "错误档案"],
    "用户档案": ["用户", "偏好", "习惯", "身份"],
    "palace_docs": ["mempalace", "记忆宫殿", "drawer", "closet"],
}

# ── 常驻服务清单（autostart_all 用）──
SERVICES = [
    {
        "name": "mem_service",
        "port": PORT_MEM_SERVICE,
        "cmd": None,   # 由 autostart_all 填充（pythonw mem_service.py）
        "desc": "记忆检索常驻",
    },
]


def ensure_dirs():
    """确保关键目录存在"""
    for d in (ROOT, LOG_DIR, SESSIONS, EXPERIENCE, NOTES):
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    import json
    print(json.dumps({
        "ROOT": ROOT, "CHROMA_DB": CHROMA_DB, "SQLITE_DB": SQLITE_DB,
        "AUTONOMY": AUTONOMY, "LOG_DIR": LOG_DIR,
        "ports": {"mem": PORT_MEM_SERVICE, "compress": PORT_COMPRESS_PROXY,
                  "llm": PORT_LLM_POOL, "hub": PORT_HUB},
        "mempalace_cli": MEMPALACE_CLI,
        "llm": {"endpoint": LLM_ENDPOINT, "model": LLM_MODEL},
        "wings": len(WING_KEYWORDS),
    }, ensure_ascii=False, indent=2))
