"""评测 CLI 入口 — 完全独立于项目后端。

用法:
    python -m evaluation.eval export --name my_dataset --limit 100   # 从日志导出数据集
    python -m evaluation.eval run --dataset-name my_dataset          # 对数据集执行评测
    python -m evaluation.eval list                                   # 列出所有数据集
    python -m evaluation.eval history --dataset-name my_dataset      # 查看历史评测
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime

# 确保项目根目录在 sys.path 中（支持直接 python evaluation/eval.py 运行）
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from evaluation.config import LOGS_DIR, DATA_DIR
from evaluation.log_parser import parse_llm_trace
from evaluation.dataset_manager import EvalDatasetManager
from evaluation.eval_runner import get_eval_runner
from evaluation.db import get_eval_summary, get_eval_results

logger = logging.getLogger("evaluation")


def setup_logging():
    """配置评测脚本日志（输出到控制台）。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def cmd_export(args):
    """从生产日志导出数据集（JSON 文件）。

    工作流：
    1. 系统运行产生 llm_trace.log
    2. 从日志解析出真实问答对 → 导出为 JSON 数据集
    3. 可选人工补充 reference（参考答案）以支持 ContextRecall 评测
    """
    log_path = args.log_path or os.path.join(LOGS_DIR, "llm_trace.log")
    name = args.name or f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    print(f"📋 从日志解析: {log_path}")
    samples = parse_llm_trace(
        log_path=log_path,
        limit=args.limit,
        session_id=args.session_id or None,
    )

    if not samples:
        print("⚠️  日志中没有找到包含检索的对话样本")
        return

    mgr = EvalDatasetManager()
    export_samples = []
    for s in samples:
        export_samples.append({
            "question": s["question"],
            "answer": s["answer"],
            "contexts": s["contexts"],
            "reference": "",  # 留空，待人工补充
        })

    fpath = mgr.save_dataset(name, export_samples)
    print(f"✅ 已导出 {len(export_samples)} 条样本 → {fpath}")
    print()
    print("💡 提示：")
    print("   1. 如需 ContextRecall 评测，请编辑该 JSON，手动补充 reference 字段")
    print("   2. 运行评测: python -m evaluation.eval run --dataset-name " + name)


def cmd_run(args):
    """对数据集执行 RAGAS 评测。"""
    dataset_name = args.dataset_name
    mgr = EvalDatasetManager()

    # 加载数据集
    try:
        samples = mgr.load_dataset(dataset_name)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    if not samples:
        print(f"⚠️  数据集 {dataset_name} 为空")
        return

    # 解析指标
    metrics = [m.strip() for m in args.metrics.split(",") if m.strip()]
    valid_metrics = {"faithfulness", "answer_relevancy", "context_precision", "context_recall"}
    metrics = [m for m in metrics if m in valid_metrics]
    if not metrics:
        print("❌ 没有有效的评测指标")
        sys.exit(1)

    print(f"📦 数据集: {dataset_name}")
    print(f"🔬 评测指标: {', '.join(metrics)}")
    print(f"📊 样本数量: {len(samples)}")
    print(f"{'─'*50}")

    # 执行评测
    runner = get_eval_runner()
    result = runner.run(samples, metrics, dataset_name)

    # 打印汇总
    print(f"\n{'='*50}")
    print(f"📊 评测完成: {dataset_name}")
    print(f"{'='*50}")
    print(f"  总样本数:    {result['total_samples']}")
    print(f"  成功:        {result['success_count']}")
    print(f"  失败:        {result['failed_count']}")
    print(f"  总耗时:      {result['total_latency_ms']}ms")
    print(f"{'─'*50}")
    for m in metrics:
        val = result.get(f"avg_{m}")
        if val is not None:
            bar = "█" * int(val * 20)
            print(f"  {m:<22s}: {val:.4f} {bar}")
        else:
            print(f"  {m:<22s}: N/A")
    print(f"{'='*50}\n")

    # 结果已写入 MySQL
    print(f"💾 结果已写入 MySQL eval_results 表（dataset_name={dataset_name}）")

    # 同时保存汇总 JSON
    output_dir = args.output_dir or os.path.join(DATA_DIR, "eval_results")
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, f"{dataset_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"📄 汇总已保存至: {json_path}")


def cmd_list_datasets():
    """列出可用数据集（含历史运行记录）。"""
    mgr = EvalDatasetManager()
    file_datasets = mgr.list_datasets()

    # 合并数据库中已有运行记录
    db_meta = {}
    try:
        from evaluation.db import _get_conn
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        dataset_name,
                        COUNT(*) AS total,
                        SUM(CASE WHEN error_message IS NULL THEN 1 ELSE 0 END) AS success,
                        SUM(CASE WHEN error_message IS NOT NULL THEN 1 ELSE 0 END) AS failed,
                        MAX(created_at) AS last_run
                    FROM eval_results
                    GROUP BY dataset_name
                    ORDER BY last_run DESC
                    """
                )
                db_meta = {r["dataset_name"]: r for r in cur.fetchall()}
        finally:
            conn.close()
    except Exception as e:
        logger.warning("无法连接数据库读取历史记录: %s", e)

    if not file_datasets:
        print("暂无数据集文件。")
        print("创建方式：")
        print("  1. python -m evaluation.eval export --name my_dataset  （从日志导出）")
        print("  2. 手动在 data/eval_datasets/ 下放置 JSON 文件")
        return

    print(f"\n{'='*70}")
    print(f"{'数据集名称':<30} {'样本数':>6} {'有参考答案':>8} {'历史运行':>8}")
    print(f"{'-'*70}")
    for ds in file_datasets:
        meta = db_meta.get(ds["name"], {})
        print(f"{ds['name']:<30} {ds['sample_count']:>6} {'是' if ds['has_reference'] else '否':>8} "
              f"{str(meta.get('total', 0)):>8}")
    print(f"{'='*70}\n")


def cmd_history(args):
    """查看历史评测结果。"""
    dataset_name = args.dataset_name or None
    limit = args.limit

    summary = get_eval_summary(dataset_name)
    samples = get_eval_results(dataset_name, limit)

    if not summary or summary.get("total_samples", 0) == 0:
        print("暂无评测数据。请先运行评测。")
        return

    print(f"\n{'='*70}")
    print(f"📊 评测汇总{' — ' + dataset_name if dataset_name else ''}")
    print(f"{'='*70}")
    print(f"  总样本数:         {summary['total_samples']}")
    print(f"  平均忠实度:        {summary['avg_faithfulness']:.4f}")
    print(f"  平均切题度:        {summary['avg_answer_relevancy']:.4f}")
    print(f"  平均上下文精准度:  {summary['avg_context_precision']:.4f}")
    print(f"  平均上下文召回率:  {summary['avg_context_recall']:.4f}")
    print(f"  平均评测耗时:      {summary['avg_latency_ms']:.0f}ms")
    print(f"{'='*70}")

    if samples:
        print(f"\n最近 {min(10, len(samples))} 条明细:")
        print(f"{'─'*70}")
        for s in samples[:10]:
            q = (s.get("question", "") or "")[:50]
            f_val = f"{s.get('faithfulness', 0):.3f}" if s.get("faithfulness") is not None else "-"
            ar_val = f"{s.get('answer_relevancy', 0):.3f}" if s.get("answer_relevancy") is not None else "-"
            status = "❌" if s.get("error_message") else "✅"
            print(f"  {status} {q}...  Faith:{f_val}  AR:{ar_val}")
        print(f"{'─'*70}\n")


def main():
    parser = argparse.ArgumentParser(
        description="RAGAS 评测工具 — 独立于项目后端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m evaluation.eval export --name my_dataset --limit 100
  python -m evaluation.eval run --dataset-name my_dataset
  python -m evaluation.eval list
  python -m evaluation.eval history --dataset-name my_dataset
        """,
    )

    sub = parser.add_subparsers(dest="command", help="子命令")

    # export — 从日志导出数据集
    export_parser = sub.add_parser("export", help="从日志导出数据集（JSON 文件）")
    export_parser.add_argument("--name", default=None,
                               help="数据集名称 (default: export_YYYYMMDD_HHMMSS)")
    export_parser.add_argument("--limit", type=int, default=100,
                               help="从日志抽取条数 (default: 100)")
    export_parser.add_argument("--session-id", default=None, help="筛选指定会话")
    export_parser.add_argument("--log-path", default=None,
                               help="日志路径 (default: logs/llm_trace.log)")

    # run — 对数据集执行评测
    run_parser = sub.add_parser("run", help="对数据集执行 RAGAS 评测")
    run_parser.add_argument("--dataset-name", required=True, help="数据集名称（必填）")
    run_parser.add_argument("--metrics", default="faithfulness,answer_relevancy,context_precision",
                            help="评测指标，逗号分隔 (default: faithfulness,answer_relevancy,context_precision)")
    run_parser.add_argument("--output-dir", default=None,
                            help="汇总 JSON 输出目录 (default: data/eval_results/)")

    # list
    list_parser = sub.add_parser("list", help="列出可用数据集")

    # history
    hist_parser = sub.add_parser("history", help="查看历史评测结果")
    hist_parser.add_argument("--dataset-name", default=None, help="筛选数据集")
    hist_parser.add_argument("--limit", type=int, default=100, help="明细条数 (default: 100)")

    args = parser.parse_args()

    setup_logging()

    if args.command == "export":
        cmd_export(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "list":
        cmd_list_datasets()
    elif args.command == "history":
        cmd_history(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
