"""数据集管理 — 管理 data/eval_datasets/ 下的 JSON 评测数据集。"""

import json
import logging
import os

from evaluation import config

logger = logging.getLogger(__name__)


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
