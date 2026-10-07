# Historical Qwen3.6 27B reference

The original repository revision documents Qwen3.6-27B BF16. Its complete guide and scripts are retained in [commit 4271fb7](https://github.com/qiuhanzhang616-arch/qwen3.6-27b-modelarts-standard/tree/4271fb7210f1cb7bc57fbdd7126918995dd0a073).

That model used a dense architecture and a different weight snapshot. The earlier deployment passed ordinary chat, streaming Unicode JSON, multi-turn chat, default thinking and a 261,797-input-token request. It was subsequently stopped with zero active requests. These are historical 27B observations only.

The current guide targets **Qwen3.6-35B-A3B**, a MoE model with different weights, architecture and expert parallelism. No 35B deployment, quality, long-context, throughput, shutdown or restart acceptance result has been obtained by this documentation update. Run the supplied checks with the selected 35B model on the actual target pool.

The existing repository URL is retained for link continuity; the README and current guide identify the 35B target explicitly.
