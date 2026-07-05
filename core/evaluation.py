"""RAGAS 离线评测模块。

完全独立于线上 RagService，不修改核心 RAG 逻辑。
支持两种数据源：
  1. 解析 logs/llm_trace.log 提取真实问答+检索上下文
  2. 加载 data/eval_datasets/*.json 数据集
"""

import json
import logging
import os
import re
import threading
import time
from datetime import datetime
from typing import Optional

from core import config
from core.database import (
    insert_eval_results,
    get_eval_results,
    get_eval_summary,
)

logger = logging.getLogger(__name__)

# ── 日志解析 ────────────────────────────────────────────

# 日志块分隔符: ══════ iterN REQUEST/RESPONSE session=XXX ══════
_BLOCK_RE = re.compile(
    r"╔{6} iter(\d+) (REQUEST|RESPONSE) session=(\S+) (?:\([\d.]+s\) )?╔{6}"
)

# 也匹配日志中实际使用的全角/半角变体
_BLOCK_RE_LOOSE = re.compile(
    r"={2,}\s*iter(\d+)\s+(REQUEST|RESPONSE)\s+session=(\S+).*={2,}"
)


def parse_llm_trace(
    log_path: str | None = None,
    limit: int = 50,
    session_id: str | None = None,
) -> list[dict]:
    """解析 llm_trace.log，提取 question-answer-contexts 三元组。

    只提取发生过检索（有 ToolMessage）的会话，这些才有评测意义。

    Args:
        log_path: 日志路径，默认 config.BASE_DIR/logs/llm_trace.log
        limit: 最多返回多少条样本
        session_id: 只提取指定会话（可选）

    Returns:
        [{question, answer, contexts, session_id}]
    """
    if log_path is None:
        log_path = os.path.join(config.BASE_DIR, "logs", "llm_trace.log")

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
            # 可能是跨块切分不完整，尝试在末尾补全
            try:
                # 响应是单个对象，不是数组
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


# ── 数据集管理 ──────────────────────────────────────────

class EvalDatasetManager:
    """管理 data/eval_datasets/ 下的 JSON 评测数据集。"""

    def __init__(self):
        self._datasets_dir = os.path.join(config.DATA_DIR, "eval_datasets")
        os.makedirs(self._datasets_dir, exist_ok=True)

    def list_datasets(self) -> list[dict]:
        """列出所有可用数据集。"""
        datasets = []
        if not os.path.isdir(self._datasets_dir):
            return datasets
        for fname in sorted(os.listdir(self._datasets_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self._datasets_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                logger.warning("跳过无效数据集文件 %s", fname)
                continue
            samples = data if isinstance(data, list) else data.get("samples", [])
            has_ref = any(s.get("reference") for s in samples if isinstance(s, dict))
            datasets.append({
                "name": fname[:-5],
                "sample_count": len(samples),
                "has_reference": has_ref,
            })
        return datasets

    def load_dataset(self, name: str) -> list[dict]:
        """加载指定数据集，返回样本列表。"""
        fpath = os.path.join(self._datasets_dir, f"{name}.json")
        if not os.path.exists(fpath):
            raise FileNotFoundError(f"数据集不存在: {name}")
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        samples = data if isinstance(data, list) else data.get("samples", [])
        # 标准化字段名
        result = []
        for s in samples:
            result.append({
                "question": s.get("question", ""),
                "answer": s.get("answer", ""),
                "reference": s.get("reference", s.get("ground_truth", "")),
                "contexts": s.get("contexts", []),
            })
        return result

    def save_dataset(self, name: str, samples: list[dict]) -> str:
        """保存数据集到 JSON 文件（如从日志解析结果导出）。"""
        fpath = os.path.join(self._datasets_dir, f"{name}.json")
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(samples, f, ensure_ascii=False, indent=2)
        logger.info("数据集已保存 name=%s samples=%d", name, len(samples))
        return fpath


# ── RAGAS 评测执行 ──────────────────────────────────────

# RAGAS 指标名 → 类映射
_METRIC_REGISTRY = {
    "faithfulness": ("Faithfulness", True),       # (类名, 需要LLM)
    "answer_relevancy": ("AnswerRelevancy", True),
    "context_precision": ("ContextPrecision", True),
    "context_recall": ("ContextRecall", True),
}


class EvalRunner:
    """封装 RAGAS evaluate() 调用，延迟初始化评测 LLM 和 Embeddings。"""

    def __init__(self):
        self._evaluator_llm = None
        self._evaluator_embeddings = None

    def _get_evaluator_llm(self):
        """延迟初始化 DeepSeek 评测 LLM。"""
        if self._evaluator_llm is None:
            from openai import AsyncOpenAI
            from ragas.llms import llm_factory

            client = AsyncOpenAI(
                api_key=config.DEEPSEEK_API_KEY,
                base_url=f"{config.DEEPSEEK_BASE_URL}/v1",
            )
            self._evaluator_llm = llm_factory(
                "deepseek-chat",
                provider="openai",
                client=client,
            )
            logger.info("RAGAS 评测 LLM 已初始化 model=deepseek-chat")
        return self._evaluator_llm

    def _get_embeddings(self):
        """延迟初始化 DashScope embeddings（供 RAGAS 内部使用）。"""
        if self._evaluator_embeddings is None:
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from langchain_community.embeddings import DashScopeEmbeddings
            self._evaluator_embeddings = LangchainEmbeddingsWrapper(
                DashScopeEmbeddings(model="text-embedding-v4")
            )
            logger.info("RAGAS 评测 Embeddings 已初始化 model=text-embedding-v4")
        return self._evaluator_embeddings

    def run(
        self,
        samples: list[dict],
        metrics: list[str],
        dataset_name: str,
    ) -> dict:
        """执行 RAGAS 评测，结果写入 MySQL，返回汇总。

        Args:
            samples: [{question, answer, contexts, reference?}]
            metrics: 指标名列表，如 ["faithfulness", "answer_relevancy"]
            dataset_name: 数据集名称（用于结果分组）

        Returns:
            {total_samples, success_count, failed_count, avg_XXX, ...}
        """
        if not samples:
            return {
                "dataset_name": dataset_name,
                "total_samples": 0,
                "success_count": 0,
                "failed_count": 0,
            }

        total_start = time.time()
        evaluator_llm = self._get_evaluator_llm()
        evaluator_embeddings = self._get_embeddings()

        # 1. 构建 RAGAS 指标实例
        from ragas.metrics import (
            Faithfulness,
            AnswerRelevancy,
            ContextPrecision,
            ContextRecall,
        )

        _CLS_MAP = {
            "faithfulness": Faithfulness,
            "answer_relevancy": AnswerRelevancy,
            "context_precision": ContextPrecision,
            "context_recall": ContextRecall,
        }

        selected_metrics = []
        for m in metrics:
            cls = _CLS_MAP.get(m)
            if cls is None:
                logger.warning("未知指标: %s，已跳过", m)
                continue
            # 需要 LLM 的指标传入 evaluator_llm
            if _METRIC_REGISTRY.get(m, (None, True))[1]:
                selected_metrics.append(cls(llm=evaluator_llm))
            else:
                selected_metrics.append(cls())

        if not selected_metrics:
            return {
                "dataset_name": dataset_name,
                "total_samples": len(samples),
                "success_count": 0,
                "failed_count": len(samples),
                "message": "没有可用的评测指标",
            }

        # 2. 分批执行 RAGAS 评测（逐样本，避免单次失败影响全部）
        from ragas import EvaluationDataset, SingleTurnSample, evaluate

        run_results = []
        valid_indices = []
        all_ragas_samples = []

        for i, s in enumerate(samples):
            question = s.get("question", "")
            answer = s.get("answer", "")
            contexts = s.get("contexts", [])
            reference = s.get("reference", "")

            sample_start = time.time()
            error_msg = None

            try:
                ragas_sample = SingleTurnSample(
                    user_input=question,
                    response=answer or "",
                    retrieved_contexts=contexts if contexts else [],
                    reference=reference or None,
                )
                all_ragas_samples.append(ragas_sample)
                valid_indices.append(i)

                run_results.append({
                    "dataset_name": dataset_name,
                    "question": question[:1000],
                    "answer": (answer or "")[:10000],
                    "contexts": json.dumps(contexts, ensure_ascii=False),
                    "reference": (reference or "")[:2000],
                    "eval_latency_ms": int((time.time() - sample_start) * 1000),
                    "error_message": None,
                })
            except Exception as e:
                error_msg = str(e)[:1000]
                logger.error("样本 %d RAGAS 构建失败: %s", i, e)
                run_results.append({
                    "dataset_name": dataset_name,
                    "question": question[:1000],
                    "answer": (answer or "")[:10000],
                    "contexts": json.dumps(contexts, ensure_ascii=False),
                    "reference": (reference or "")[:2000],
                    "eval_latency_ms": int((time.time() - sample_start) * 1000),
                    "error_message": error_msg,
                })

        # 3. 调用 RAGAS evaluate()
        if all_ragas_samples:
            try:
                eval_dataset = EvaluationDataset(samples=all_ragas_samples)
                ragas_result = evaluate(
                    dataset=eval_dataset,
                    metrics=selected_metrics,
                    embeddings=evaluator_embeddings,
                )
                ragas_df = ragas_result.to_pandas()

                # 将 RAGAS 分数合并回 run_results
                for j, idx in enumerate(valid_indices):
                    for m in metrics:
                        if m in ragas_df.columns:
                            val = ragas_df.iloc[j][m]
                            if val is not None:
                                try:
                                    run_results[idx][m] = float(val)
                                except (ValueError, TypeError):
                                    pass
            except Exception as e:
                logger.error("RAGAS evaluate() 执行失败: %s", e)
                for idx in valid_indices:
                    if not run_results[idx].get("error_message"):
                        run_results[idx]["error_message"] = f"RAGAS error: {str(e)[:800]}"

        # 4. 填充缺失的指标字段为 None
        all_metric_keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
        for row in run_results:
            for m in all_metric_keys:
                if m not in row:
                    row[m] = None

        # 5. 持久化
        insert_eval_results(run_results)

        total_elapsed = int((time.time() - total_start) * 1000)
        success_count = len(valid_indices)
        failed_count = len(run_results) - success_count

        # 6. 计算平均值
        result = {
            "dataset_name": dataset_name,
            "total_samples": len(run_results),
            "success_count": success_count,
            "failed_count": failed_count,
            "total_latency_ms": total_elapsed,
        }
        for m in metrics:
            values = [r[m] for r in run_results if r.get(m) is not None]
            result[f"avg_{m}"] = round(sum(values) / len(values), 4) if values else None

        logger.info(
            "评测完成 dataset=%s samples=%d success=%d failed=%d elapsed=%dms %s",
            dataset_name, len(run_results), success_count, failed_count, total_elapsed,
            ", ".join(f"{k}={v}" for k, v in result.items() if k.startswith("avg_")),
        )
        return result


# ── 全局单例 ────────────────────────────────────────────

_eval_runner: EvalRunner | None = None
_eval_dataset_mgr: EvalDatasetManager | None = None
_lock = threading.Lock()


def get_eval_runner() -> EvalRunner:
    global _eval_runner
    if _eval_runner is None:
        with _lock:
            if _eval_runner is None:
                _eval_runner = EvalRunner()
    return _eval_runner


def get_eval_dataset_manager() -> EvalDatasetManager:
    global _eval_dataset_mgr
    if _eval_dataset_mgr is None:
        with _lock:
            if _eval_dataset_mgr is None:
                _eval_dataset_mgr = EvalDatasetManager()
    return _eval_dataset_mgr
