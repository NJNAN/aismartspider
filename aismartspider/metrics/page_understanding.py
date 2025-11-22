from typing import List


def compute_page_type_accuracy(gold_types: List[str], pred_types: List[str]) -> float:
    if not gold_types:
        return 0.0
    assert len(gold_types) == len(pred_types)
    correct = sum(int(g == p) for g, p in zip(gold_types, pred_types))
    return correct / max(len(gold_types), 1)
