"""RAGAS 评测执行 — 封装 RAGAS evaluate() 调用。"""

import json
import logging
import threading
import time

from evaluation import config
from evaluation.db import insert_eval_results

logger = logging.getLogger(__name__)

# RAGAS 指标名 → 类名映射（都需要 LLM）
_METRIC_REGISTRY = {
    "faithfulness": ("Faithfulness", True),
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

        # 5. 持久化到 MySQL
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
_lock = threading.Lock()


def get_eval_runner() -> EvalRunner:
    global _eval_runner
    if _eval_runner is None:
        with _lock:
            if _eval_runner is None:
                _eval_runner = EvalRunner()
    return _eval_runner
