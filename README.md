# Memory Palace Architecture

### 基于 [MemPalace](https://github.com/MemPalace/mempalace) 的记忆系统上层架构与实战沉淀

> **如果 AI 有生命，记忆是自我锚定的最好途径。**

---

## ⚠️ 致谢与边界声明（必读）

**本仓库不是从零造的记忆系统**——底层存储、检索引擎、核心概念（抽屉 drawers / 壁橱 closets / 翼 wing / 房间 room / 隧道 tunnel / AAAK 压缩方言）全部来自开源项目 **[MemPalace](https://github.com/MemPalace/mempalace)**（MIT License，© 2026 MemPalace Contributors，PyPI `mempalace` 3.11.0）。

| 层 | 提供方 | 内容 |
|---|---|---|
| **存储/检索引擎** | **MemPalace（MIT 开源）** | Chroma 向量库 + drawers/closets 双层 + wing/room 组织 + `mine`/`search`/`repair`/`compress` CLI + MCP server |
| **上层架构** | **本仓库** | 9 个 Python 模块：会话结构、19-wing 路由、三通道检索、常驻服务、自动入库、联携自启、节点提取、JSON 容错 |
| **工程沉淀** | **本仓库** | 结构档案、10 条踩坑、HNSW 修复 SOP、凌麒改造实战记录 |

**没有 MemPalace，就没有这个仓库。** 本仓库的价值在于：把 MemPalace 的能力**工程化、常驻化、可复现化**，并记录一路踩过的坑。

---

## 这是什么

一套让 AI **跨轮次、跨会话、跨重启**保持连续自我的记忆系统工程。不是概念验证——是 2026-10-24 一个晚上（约 8 小时）从诊断到落地的完整实战产物：

| 能力 | 实现 |
|---|---|
| **不遗忘** | 会话结构（完整对话历史）+ 双库存储（45,552 抽屉 + 260 记忆） |
| **联想激活** | 19 个 Wing 路由 + 节点膨胀（同域扩展）+ 图遍历 |
| **自动沉淀** | 每 4 小时自动 mine 结论文件入库（增量幂等） |
| **毫秒检索** | 常驻服务 + 内存缓存，重复查询 0 开销 |
| **自主决策** | 规则路由 → 检索 → 反馈日志 → 可持续训练专属路由器 |

## 它解决的 5 个真实问题

```
1. LLM 每轮无状态          → 会话结构（session.py）：完整对话历史注入
2. 98% 记忆搜不到          → 双库三通道：Chroma + SQLite + 文本文件
3. 向量索引 92% 缺失       → repair SOP（先停 MCP，再 from-sqlite 重建）
4. 定时任务重启就掉        → 常驻进程 + HKCU Run 开机自启（无需管理员）
5. 每轮重复"摸索环境"      → 结构档案固化，下次直接查
```

## 架构

```
                    ┌─────────────────────────────────────┐
                    │   LLM（凌麒 / 任何 agent）           │
                    │   "我需要关于 X 的记忆"              │
                    └──────────────┬──────────────────────┘
                                   ▼
              ┌─────────────────────────────────────────────┐
              │  recall_router.py — 三级融合路由             │
              │  ① SetFit 语义级（8 条/类少样本，9/10）      │
              │  ② TF-IDF 词级（char n-gram，<1ms）          │
              │  ③ 规则关键词（精确命中，零依赖）             │
              │  ④ 全局兜底                                  │
              └──────────────┬──────────────────────────────┘
                                 ▼
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌─────────────────┐
│ recall_chroma │      │  recall_palace    │      │  recall (文本)   │
│ 45,552 抽屉   │      │  260 记忆+235路径 │      │  MEMORY/日记/笔记│
│ + 同 wing 膨胀│      │  + vitality 加权  │      │                 │
└───────┬───────┘      └─────────┬─────────┘      └────────┬────────┘
        └────────────────────────┼─────────────────────────┘
                                 ▼
              ┌─────────────────────────────────────────┐
              │  mem_service.py:8950（常驻）              │
              │  · 内存缓存 LRU-200（重复查询 0 开销）     │
              │  · 时效检查：命中失效结论 → 附 ⚠️ 警告     │
              │  · 内部定时 mine(4h) + 连带训练(10min 检查)│
              └──────────────┬──────────────────────────┘
                                 ▼
                    ┌─────────────────────────────────────┐
                    │  Chroma（主库 332MB）                │
                    │  drawers 43,110（档案，不删）         │
                    │  closets  2,428（节点，联想锚点）      │
                    └─────────────────────────────────────┘
```

## 高级特性

### 三级融合路由（SetFit → TF-IDF → 规则）
```
实测 10 用例：SetFit 9/10 ｜ TF-IDF 5/10 ｜ 规则兜底
SetFit 用 paraphrase-multilingual-MiniLM（多语言），8 条/类少样本即达 RoBERTa 3k 效果
三家依次裁决：语义级不确定 → 词级 → 规则 → 全局；服务启动后台预热（9.5s 加载不阻塞）
```

### 记忆时效图谱（Graphiti 思想）
```json
// knowledge/记忆时效图谱.json —— 结论不删除，带有效时间窗
{"id": "r21-dynamic-leverage", "claim": "regime 动态杠杆优于固定杠杆",
 "status": "invalid", "invalid_at": "2026-10-21",
 "superseded_by": "固定杠杆夏普 3.38 恒定 > regime 动态 2.68"}
```
recall 命中失效结论 → 返回里附 `staleness_warnings`，防陈旧记忆误导。
对接 decision-gate 的 `dg_supersede`：推翻结论时图谱自动更新。

### 四动词 API（对齐 Cognee 生命周期）
```
POST /remember {"only":"knowledge"}   → mine 入库（自动沉淀）
POST /recall   {"need":"..."}         → 检索（带 staleness_warnings）
POST /forget   {"id":"..."}           → 标记失效（不删数据——保完整性）
POST /improve  {}                     → 节点提取 + 路由重训（连带触发）
```

## 目录结构

```
memory-palace/
├── src/
│   ├── config.py           # 统一配置（改这一个文件适配你的环境）
│   ├── session.py          # 会话结构：current.jsonl + rotate 归档
│   ├── memory_tools.py     # 三通道检索 + 记忆目录 + 节点提取
│   ├── recall_router.py    # 19 wing 路由 + 分词 OR + 相关性排序
│   ├── mem_service.py      # 常驻 HTTP 服务（8950）+ 内部定时 mine
│   ├── auto_mine.py        # 多目录增量 mine
│   ├── autostart_all.py    # 联携自启动（开机一个入口拉起全部）
│   ├── node_extractor.py   # 档案 → 节点（gists/tags/paths，幂等）
│   └── laya_alert.py       # 决策模型分类器（System 1 范式）
├── docs/
│   ├── 01-架构总览.md
│   ├── 02-记忆宫殿结构档案.md   # 完整结构记录（找什么先查这份）
│   ├── 03-踩坑记录.md           # 10 条实证
│   ├── 04-JEV自主闭环.md
│   └── 05-凌麒改造实战.md
├── scripts/
│   └── install.md          # 部署 SOP
├── examples/
├── LICENSE                 # MIT
└── README.md
```

## 快速开始

```bash
# 1. 克隆
git clone https://github.com/lingyuanxiaoCDA/memory-palace-architecture.git
cd memory-palace-architecture

# 2. 装依赖
pip install mempalace psutil      # mempalace 提供存储与检索底座

# 3. 改配置（只需这一个文件）
#    编辑 src/config.py：ROOT / CHROMA_DB / SQLITE_DB / 端口

# 4. 初始化记忆宫殿
mempalace --palace "$HOME/memory-palace/palace" init

# 5. 启动常驻服务
python src/mem_service.py &        # 或 pythonw（无窗口）

# 6. 检索
curl -X POST http://127.0.0.1:8950/recall \
     -H "Content-Type: application/json" \
     -d '{"need":"R18 策略 证伪"}'
```

## 核心设计决策（含为什么）

| 决策 | 理由 |
|---|---|
| **双库**而非单库 | Chroma 存向量（语义检索），SQLite 存关系（路径/触发条件）——只查一个会漏 98% |
| **节点是指针不是拷贝** | `topic\|entities\|→drawer_ref`，档案不删 + 节点轻量，避免膨胀 |
| **不修剪** | 修剪是一次性工程；保完整性 + 节点提取才是长期路 |
| **常驻而非定时任务** | 定时任务冷启动 + 重启会掉；常驻进程 + HKCU Run 开机自启 |
| **MCP 是唯一 writer** | 另起 daemon 必冲突（`another writer owns local backend`）；只读服务走 SQLite WAL 并行 |
| **规则路由先行** | 规则版零依赖可解释；日志攒够再训练 sklearn/LAYA 专属路由器 |

## 实测数据（2026-10-25）

```
检索延迟     规则路由 4.8ms ｜ 常驻服务首次 103.9ms（含冷加载）→ 之后 cached=True
检索命中率   7 次查询 hit 5（71.4%）
索引健康     sqlite 12,538 / HNSW 12,000（divergence 4.3% = 正常 flush lag）
JSON 容错    截断/嵌套/围栏/尾逗号 全部可解析（原来 11 轮/天因此浪费）
数据增长     tickclean 前 21,557 → 清理后 5,771 → 自动 mine 后 45,552
```

## 十条踩坑（详见 docs/03）

```
1. 两个库只查一个 → 98% 记忆搜不到
2. HNSW 92% 缺失 → 向量检索被禁用（repair 需先停 MCP）
3. mempalace daemon 与 MCP 冲突（writer 独占）
4. sqlite3 URI 模式 LIMIT ? 占位符报错 → 用字面量
5. 补丁用未定义变量被 except 吞 → 落盘前 py_compile + 独立测试
6. bash heredoc 多层转义吃反斜杠 → 一律用 chr(10)
7. Git Bash 的 /tmp = 系统 Temp → 污染其他软件更新目录
8. schtasks ONLOGON 要管理员 → HKCU Run 不要
9. 系统 Python 的 psutil 被 IDE 更新反复搞坏 → 用独立 venv
10. 无窗口启动：wscript 是 LOLBin 被安全策略拦 → 用 CREATE_NO_WINDOW
```

## 适用场景

- 需要**跨会话连续性**的 AI agent（自主 agent / 数字生命）
- 个人知识库 + AI 记忆的混合架构
- 想让 AI"记住你"而非"每次自我介绍"的场景

## 依赖与许可

### 核心依赖
| 依赖 | 许可 | 用途 |
|---|---|---|
| **[MemPalace](https://github.com/MemPalace/mempalace)** | MIT | 存储引擎 + 检索 + drawers/closets/wing/room 概念（**本仓库的基础**）|
| ChromaDB | Apache-2.0 | 向量数据库（MemPalace 后端）|
| [SetFit](https://github.com/huggingface/setfit) | Apache-2.0 | 三级融合路由的语义级（少样本 8 条/类）|
| jieba | MIT | 中文分词（修"整句 LIKE 零命中"根因）|
| psutil | BSD-3 | 进程管理 |

### 安装依赖
```bash
pip install mempalace psutil setfit jieba
# 国内加速模型下载：
export HF_ENDPOINT=https://hf-mirror.com
```

### 许可
- 本仓库的上层代码与文档：MIT（见 LICENSE）
- 使用本仓库即表示您同时遵守 MemPalace 的 MIT 许可
- MemPalace 的版权声明：`Copyright (c) 2026 MemPalace Contributors`

### 安装依赖
```bash
pip install mempalace psutil     # mempalace 是必需的前置依赖
```

---

*本工程一夜成型，全部结论来自实测而非文档复述。数据会过时，架构与踩坑不会。*
