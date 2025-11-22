import json
from collections import defaultdict
from typing import Dict, Any, List, Tuple

from aismartspider.metrics.extraction import (
    compute_field_precision_recall,
    compute_fuzzy_similarity,
)
from aismartspider.metrics.page_understanding import compute_page_type_accuracy
from aismartspider.metrics.system_metrics import aggregate_timings


def load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def index_gold_by_key(gold_runs: List[Dict[str, Any]]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """
    以 (site, url) 作为 key，把 gold 结果索引起来，方便对齐。
    """
    idx = {}
    for r in gold_runs:
        key = (r["site"], r["url"])
        idx[key] = r
    return idx


def main(gold_path: str, pred_path: str):
    gold = load_json(gold_path)
    pred = load_json(pred_path)

    gold_idx = index_gold_by_key(gold["runs"])

    # 收集指标
    page_type_results = []
    field_pr_results = []
    fuzzy_scores = []
    timings_list = []

    for run in pred["runs"]:
        key = (run["site"], run["url"])
        if key not in gold_idx:
            # 如果 gold 没标注这个 run，就跳过或者记录为未标注
            continue

        gold_run = gold_idx[key]

        # 1) 页面类型准确率
        pt_correct = (run["metrics"]["page_type"] == gold_run["page_type"])
        page_type_results.append(int(pt_correct))

        # 2) 字段精确率/召回率（结构化字段）
        gold_fields = gold_run.get("fields", {})
        pred_records = run.get("records", [])
        # 这里只示范“取第一条 record”作为预测
        pred_fields = pred_records[0] if pred_records else {}

        pr = compute_field_precision_recall(gold_fields, pred_fields)
        field_pr_results.append(pr)

        # 3) 模糊匹配得分（非结构化文本，如 content）
        fuzzy = compute_fuzzy_similarity(gold_fields, pred_fields)
        fuzzy_scores.append(fuzzy)

        # 4) 系统级耗时
        timings_list.append(run["metrics"].get("timings", {}))

    # ======== 汇总 ========
    page_type_acc = sum(page_type_results) / max(len(page_type_results), 1)

    # 平均字段精确率/召回率
    avg_precision = sum(x["precision"] for x in field_pr_results) / max(len(field_pr_results), 1)
    avg_recall = sum(x["recall"] for x in field_pr_results) / max(len(field_pr_results), 1)
    avg_f1 = sum(x["f1"] for x in field_pr_results) / max(len(field_pr_results), 1)

    # 模糊匹配平均得分
    avg_fuzzy = sum(fuzzy_scores) / max(len(fuzzy_scores), 1)

    # 耗时统计
    timing_summary = aggregate_timings(timings_list)

    print("=== Page Understanding ===")
    print(f"Page Type Accuracy: {page_type_acc:.3f}")

    print("\n=== Extraction Quality ===")
    print(f"Field Precision: {avg_precision:.3f}")
    print(f"Field Recall:    {avg_recall:.3f}")
    print(f"Field F1:        {avg_f1:.3f}")
    print(f"Fuzzy Score:     {avg_fuzzy:.3f}")

    print("\n=== System Performance ===")
    for k, v in timing_summary.items():
        print(f"{k}: mean={v['mean']:.3f}s, std={v['std']:.3f}s, min={v['min']:.3f}s, max={v['max']:.3f}s")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", required=True)
    parser.add_argument("--pred", required=True)
    args = parser.parse_args()

    main(args.gold, args.pred)
