# Day 2 model comparison

One `run_id` (`8359383e-262f-44a5-b386-5e797b534814`). Twelve summarization cases. Same prompt (`baseline` / `v0`), temperature `0.0`, and `max_output_tokens=512`. Both models `provider="ollama"`. Local provider charge is `0.0` for every record; this comparison does not use dollar cost.

| Model | Success | Input tokens | Output tokens | Median latency | Max latency |
| --- | --- | --- | --- | --- | --- |
| `mistral:7b` | 12/12 | 2,679 | 1,602 | 6,006 ms | 11,299 ms |
| `qwen3:8b` | 8/12 | 2,355 | 4,887 | 21,808.5 ms | 33,538 ms |

Qwen hit the shared 512 output-token ceiling on S01, S04, S05, and S06 (`TruncatedResponseError`, not retried). Mistral finished every case under that ceiling. Qwen also wrote about three times as many output tokens and had a median latency about 3.6× Mistral’s on the same requests, so output length—not the input document—dominated this run’s workload.
