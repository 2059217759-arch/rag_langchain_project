"""日志解析 — 从 llm_trace.log 提取 question-answer-contexts 三元组。"""

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── 正则 ────────────────────────────────────────────

# 日志块分隔符: ══════ iterN REQUEST/RESPONSE session=XXX ══════
_BLOCK_RE = re.compile(
    r"╔{6} iter(\d+) (REQUEST|RESPONSE) session=(\S+) (?:\([\d.]+s\) )?╔{6}"
)

# 也匹配日志中实际使用的全角/半角变体
_BLOCK_RE_LOOSE = re.compile(
    r"={2,}\s*iter(\d+)\s+(REQUEST|RESPONSE)\s+session=(\S+).*={2,}"
)


def parse_llm_trace(
    log_path: str,
    limit: int = 50,
    session_id: str | None = None,
) -> list[dict]:
    """解析 llm_trace.log，提取 question-answer-contexts 三元组。

    只提取发生过检索（有 ToolMessage）的会话，这些才有评测意义。

    Args:
        log_path: 日志文件路径
        limit: 最多返回多少条样本
        session_id: 只提取指定会话（可选）

    Returns:
        [{question, answer, contexts, session_id}]
    """
    if not os.path.exists(log_path):
        logger.warning("llm_trace.log 不存在: %s", log_path)
        return []

    # 1. 将日志拆成 (session, iter, type, json_str) 块
    blocks = _split_log_blocks(log_path)
    if not blocks:
        return []

    # 2. 按 session 分组
    sessions: dict[str, dict] = {}
    for blk in blocks:
        sid = blk["session"]
        if session_id and sid != session_id:
            continue
        if sid not in sessions:
            sessions[sid] = {"requests": {}, "responses": {}}
        if blk["type"] == "REQUEST":
            sessions[sid]["requests"][blk["iter"]] = blk["json"]
        else:
            sessions[sid]["responses"][blk["iter"]] = blk["json"]

    # 3. 从每个 session 中提取 question + answer + contexts
    samples = []
    for sid, data in sessions.items():
        reqs = data["requests"]
        resps = data["responses"]

        # 找最后一轮迭代
        if not reqs:
            continue
        max_iter = max(reqs.keys())
        request_msgs = reqs.get(max_iter, [])
        response_msg = resps.get(max_iter, {})

        if not isinstance(request_msgs, list):
            continue

        # 提取问题（最后一条 human 消息）
        question = ""
        for msg in reversed(request_msgs):
            if isinstance(msg, dict) and msg.get("type") == "human":
                question = (msg.get("data", {}) or {}).get("content", "")
                break
        if not question:
            continue

        # 提取检索上下文（所有 tool 消息）
        contexts = []
        for msg in request_msgs:
            if isinstance(msg, dict) and msg.get("type") == "tool":
                ctx = (msg.get("data", {}) or {}).get("content", "")
                if ctx and "未找到" not in ctx:
                    contexts.append(ctx)

        # 只保留发生过检索的样本
        if not contexts:
            continue

        # 提取答案（response 中的 content）
        answer = ""
        if isinstance(response_msg, dict):
            answer = (response_msg.get("data", {}) or {}).get("content", "")

        if not answer:
            continue

        samples.append({
            "question": question.strip(),
            "answer": answer.strip(),
            "contexts": contexts,
            "session_id": sid,
        })

        if len(samples) >= limit:
            break

    logger.info("从日志解析出 %d 条评测样本（limit=%d）", len(samples), limit)
    return samples[:limit]


def _split_log_blocks(log_path: str) -> list[dict]:
    """将 llm_trace.log 拆成结构化块。"""
    with open(log_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 找到所有块边界
    matches = list(_BLOCK_RE_LOOSE.finditer(content))
    if not matches:
        return []

    blocks = []
    for i, m in enumerate(matches):
        iter_num = int(m.group(1))
        block_type = m.group(2)  # REQUEST or RESPONSE
        session = m.group(3)

        # JSON 内容从当前行结束到下一个块开始（或文件末尾）
        json_start = m.end()
        json_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        json_str = content[json_start:json_end].strip()

        # 跳过非 JSON 内容（如纯文本日志混入）
        json_str = json_str.lstrip("\n")
        if not json_str.startswith("["):
            json_str = json_str.lstrip()

        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            continue

        blocks.append({
            "session": session,
            "iter": iter_num,
            "type": block_type,
            "json": parsed,
        })

    return blocks
