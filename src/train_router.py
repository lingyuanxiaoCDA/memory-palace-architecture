# -*- coding: utf-8 -*-
"""train_router.py — 检索路由器训练器（连带式：规则合成 + 真实日志即时增强）
================================================================
用户洞察（2026-10-25）："日志攒够再训练会太慢，有可能忘记，不如做连带"

设计：不等真实数据攒够 ——
  ① 启动即用 WING_KEYWORDS **合成**初始训练集（每 wing 造 8-12 条）
  ② 真实检索日志（hit=True 的）作为高置信样本混入
  ③ 每次训练 <1 秒，可高频重训（连带：检索→日志→训练→生效 全自动）
  ④ 模型输出与规则路由**混合裁决**：模型置信度 ≥ threshold 用模型，否则回落规则

产物：
  <LOG_DIR>/router_model.joblib   训练好的模型（TF-IDF + LogisticRegression）
  <LOG_DIR>/router_train_report.json  训练报告（样本数/各 wing 数/准确率）

用法：
  python train_router.py            # 训练并保存
  python train_router.py --eval     # 训练 + 留出集评估
"""
import os
import re
import sys
import json
import time
import random

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    # 本地：从 recall_router 导入（它内嵌 WING_KEYWORDS）
    from recall_router import WING_KEYWORDS
    LOG_DIR = os.environ.get("MP_LOG_DIR", LOG_DIR)
except Exception:
    # 开源仓库：从 src/config.py 导入
    _SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
    if _SRC not in sys.path:
        sys.path.insert(0, _SRC)
    try:
        from config import WING_KEYWORDS, LOG_DIR
    except Exception:
        WING_KEYWORDS = {}
        LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_tmp")

LOG = os.path.join(LOG_DIR, "recall_router.log.jsonl")
MODEL = os.path.join(LOG_DIR, "router_model.joblib")
REPORT = os.path.join(LOG_DIR, "router_train_report.json")

MODEL_MIN_CONF = float(os.environ.get("MP_MODEL_MIN_CONF", "0.55"))
SYNTH_PER_WING = int(os.environ.get("MP_SYNTH_PER_WING", "10"))

# 造句模板（中文口语化，模拟真实需求）
TEMPLATES = [
    "{kw}相关的内容",
    "我想找{kw}的资料",
    "{kw}的结论是什么",
    "帮我查{kw}",
    "关于{kw}的记录",
    "{kw}怎么处理的",
    "上次{kw}讨论的结果",
    "{kw}状态",
    "有没有{kw}的信息",
    "{kw}相关记忆",
    "查一下{kw}",
    "{kw}的文档",
]


def load_real_logs():
    """真实检索日志 → (needs, wings, weights)；hit=True 权重 3，False 权重 1"""
    needs, wings, weights = [], [], []
    if not os.path.exists(LOG):
        return needs, wings, weights
    for line in open(LOG, encoding="utf-8", errors="replace"):
        try:
            d = json.loads(line)
            need = (d.get("need") or "").strip()
            used = d.get("used") or ""
            hit = bool(d.get("hit"))
            if not need or not used or used == "global":
                continue           # global 兜底不作为训练标签
            needs.append(need)
            wings.append(used)
            weights.append(3.0 if hit else 1.0)
        except Exception:
            continue
    return needs, wings, weights


def synthesize(seed=42):
    """用 WING_KEYWORDS 合成初始训练集（保证零真实数据也能启动）"""
    rng = random.Random(seed)
    needs, wings = [], []
    for wing, kws in WING_KEYWORDS.items():
        if not kws:
            continue
        picked = rng.sample(kws, min(len(kws), SYNTH_PER_WING))
        for kw in picked:
            tpl = rng.choice(TEMPLATES)
            needs.append(tpl.format(kw=kw))
            wings.append(wing)
    return needs, wings


def build_dataset():
    """合成 + 真实 合并去重"""
    s_need, s_wing = synthesize()
    r_need, r_wing, r_w = load_real_logs()
    needs = list(s_need)
    wings = list(s_wing)
    weights = [1.0] * len(s_need)
    for n, w, wt in zip(r_need, r_wing, r_w):
        if n not in needs:                 # 真实优先去重
            needs.append(n)
            wings.append(w)
            weights.append(wt)
        else:                              # 已存在则提升权重
            i = needs.index(n)
            weights[i] = max(weights[i], wt)
    return needs, wings, weights


def train(eval_mode=False):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    import joblib

    t0 = time.time()
    needs, wings, weights = build_dataset()
    if len(set(wings)) < 2:
        return {"ok": False, "error": f"类别不足（只有 {len(set(wings))} 类），无法训练"}

    pipe = make_pipeline(
        TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), min_df=1),
        LogisticRegression(max_iter=2000, C=3.0),
    )
    pipe.fit(needs, wings, logisticregression__sample_weight=weights)

    os.makedirs(LOG_DIR, exist_ok=True)
    joblib.dump({"pipe": pipe, "wings": sorted(set(wings)),
                 "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "n_samples": len(needs), "model_min_conf": MODEL_MIN_CONF},
                MODEL)

    rep = {
        "ok": True,
        "n_total": len(needs),
        "n_synth": len(synthesize()[0]),
        "n_real": len(load_real_logs()[0]),
        "wings": {w: wings.count(w) for w in sorted(set(wings))},
        "train_ms": round((time.time() - t0) * 1000, 1),
        "model": MODEL,
    }

    if eval_mode:
        from sklearn.model_selection import cross_val_score
        try:
            scores = cross_val_score(pipe, needs, wings, cv=min(3, min(wings.count(w) for w in set(wings)) or 2))
            rep["cv_accuracy"] = round(float(scores.mean()), 3)
        except Exception as e:
            rep["cv_error"] = str(e)[:80]

    with open(REPORT, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=2)
    return rep


_PRED_CACHE = {"m": None, "mtimes": (0, 0)}


def _load_model_cached():
    """进程内单例缓存：模型文件变了才重载（避免每次 predict 都 joblib.load，那要 1.7s）"""
    import joblib
    try:
        mt = os.path.getmtime(MODEL)
    except Exception:
        return None
    if _PRED_CACHE["m"] is None or _PRED_CACHE["mtimes"][0] != mt:
        try:
            m = joblib.load(MODEL)
            _PRED_CACHE["m"] = m
            _PRED_CACHE["mtimes"] = (mt, time.time())
        except Exception:
            return None
    return _PRED_CACHE["m"]


def predict(need):
    """用训练好的模型预测 wing。
    判据 = 边际（19 类下绝对阈值会把"明显领先"误杀）：
      top1 ≥ MIN_ABS(0.22) 且 top1 - top2 ≥ MIN_MARGIN(0.10) → 用模型
      否则返回 None，让调用方回落规则路由
    """
    if not os.path.exists(MODEL):
        return None
    try:
        m = _load_model_cached()
        if m is None:
            return None
        proba = m["pipe"].predict_proba([str(need)])[0]
        order = sorted(zip(m["wings"], (float(p) for p in proba)), key=lambda x: -x[1])
        top1, p1 = order[0]
        top2, p2 = order[1] if len(order) > 1 else ("", 0.0)
        MIN_ABS = float(os.environ.get("MP_MODEL_MIN_CONF", "0.22"))
        MIN_MARGIN = float(os.environ.get("MP_MODEL_MIN_MARGIN", "0.10"))
        if p1 < MIN_ABS or (p1 - p2) < MIN_MARGIN:
            return None
        return {"wing": top1, "conf": round(p1, 3), "margin": round(p1 - p2, 3),
                "runner_up": top2, "model": True, "trained_at": m.get("trained_at")}
    except Exception:
        return None


def main():
    args = sys.argv[1:]
    if "--predict" in args:
        i = args.index("--predict")
        if i + 1 < len(args):
            print(json.dumps(predict(args[i + 1]), ensure_ascii=False))
        return
    r = train(eval_mode="--eval" in args)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if r.get("ok"):
        print("\n=== 试预测 ===")
        for q in ["R18 双腿 证伪", "V37 验证 时区", "凌麒 心跳 漂移",
                  "回测 夏普 OOS", "OKX 下单 仓位", "速查 教程 笔记"]:
            p = predict(q)
            print(f"  {q:<22} → {p['wing'] if p else '(回落规则)'} "
                  f"{'conf='+str(p['conf']) if p else ''}")


if __name__ == "__main__":
    main()
