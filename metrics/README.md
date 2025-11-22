# Metrics Module

This module provides tools for evaluating the performance of the AI Smart Spider.

## Structure

- `page_understanding.py`: Metrics for page type classification and intent recognition accuracy.
- `extraction.py`: Metrics for field extraction quality (Precision, Recall, F1, Fuzzy Similarity).
- `system_metrics.py`: Metrics for system performance (latency/timings).

## Usage

You can run the evaluation script `eval_metrics.py` to compare a prediction JSON file against a ground truth (Gold) JSON file.

### 1. Generate Predictions
Run the experiment script to generate `result_q2.json`:
```bash
python aismartspider/examples/run_experiments.py
```

### 2. Run Evaluation
Run the evaluation script, pointing to the Gold standard and the Prediction file:
```bash
python aismartspider/examples/eval_metrics.py --gold exp_json/gold_q2.json --pred result_q2.json
```

## Metrics Explanation

- **Page Type Accuracy**: Fraction of pages where the predicted `page_type` matches the Gold standard.
- **Field Precision**: Proportion of extracted fields that are correct (present in Gold).
- **Field Recall**: Proportion of Gold fields that were successfully extracted.
- **Fuzzy Score**: A string similarity score (0-1) for text fields, useful when extraction is slightly off (e.g., extra whitespace).
