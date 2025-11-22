from typing import Dict, Any, List
from difflib import SequenceMatcher


def _string_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def compute_field_precision_recall(
    gold_fields: Dict[str, Any],
    pred_fields: Dict[str, Any],
    string_match_threshold: float = 0.7,
) -> Dict[str, float]:
    """
    针对结构化字段计算整体精确率/召回率/F1。
    简化版规则：
    - 如果值是 list：按集合交集计算 TP/FP/FN
    - 如果是 str：用模糊匹配 > 阈值算命中
    """
    tp = fp = fn = 0

    for field, gold_val in gold_fields.items():
        pred_val = pred_fields.get(field, None)

        # 1) list 类型字段
        if isinstance(gold_val, list):
            gold_set = set(map(str, gold_val))
            pred_set = set(map(str, pred_val or []))

            inter = gold_set & pred_set

            tp += len(inter)
            fp += len(pred_set - inter)
            fn += len(gold_set - inter)

        # 2) 标量字符串
        elif isinstance(gold_val, str):
            gold_str = gold_val.strip()
            pred_str = (pred_val or "").strip()

            if not gold_str:
                continue

            if not pred_str:
                fn += 1
            else:
                sim = _string_similarity(gold_str, pred_str)
                if sim >= string_match_threshold:
                    tp += 1
                else:
                    fp += 1
                    fn += 1

        # 3) 其他复杂结构，可按需要拓展
        else:
            # 简单处理：先转字符串再模糊匹配
            gold_str = str(gold_val)
            pred_str = str(pred_val) if pred_val is not None else ""
            if not pred_str:
                fn += 1
            else:
                sim = _string_similarity(gold_str, pred_str)
                if sim >= string_match_threshold:
                    tp += 1
                else:
                    fp += 1
                    fn += 1

    precision = tp / max((tp + fp), 1)
    recall = tp / max((tp + fn), 1)
    if precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
    }


IMPORTANT_FIELDS_FOR_FUZZY = ["content", "title", "sub_comments"]


def compute_fuzzy_similarity(
    gold_fields: Dict[str, Any],
    pred_fields: Dict[str, Any],
) -> float:
    """
    针对几个关键非结构化字段做模糊匹配，取平均相似度。
    """
    sims = []

    for key in IMPORTANT_FIELDS_FOR_FUZZY:
        gold_val = gold_fields.get(key)
        pred_val = pred_fields.get(key)

        if gold_val is None:
            continue

        if isinstance(gold_val, str) and isinstance(pred_val, str):
            sim = _string_similarity(gold_val.strip(), pred_val.strip())
            sims.append(sim)
        elif isinstance(gold_val, list) and isinstance(pred_val, list):
            # 对列表，取每个 gold 元素在 pred 中的最大相似度，然后平均
            if not gold_val:
                continue
            item_sims = []
            for g in gold_val:
                best = 0.0
                for p in pred_val:
                    best = max(best, _string_similarity(str(g), str(p)))
                item_sims.append(best)
            if item_sims:
                sims.append(sum(item_sims) / len(item_sims))

    if not sims:
        return 0.0
    return sum(sims) / len(sims)
