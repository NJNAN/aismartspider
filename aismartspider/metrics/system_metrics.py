from typing import List, Dict
import math


def aggregate_timings(timings_list: List[Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """
    对每种 timing (fetch, summarize, ...) 计算 mean/std/min/max
    """
    buckets = {}

    for t in timings_list:
        for k, v in t.items():
            buckets.setdefault(k, []).append(v)

    summary = {}
    for k, vals in buckets.items():
        n = len(vals)
        if n == 0:
            continue
        mean = sum(vals) / max(n, 1)
        var = sum((x - mean) ** 2 for x in vals) / max(n, 1)
        std = math.sqrt(var)
        summary[k] = {
            "mean": mean,
            "std": std,
            "min": min(vals),
            "max": max(vals),
        }

    return summary
