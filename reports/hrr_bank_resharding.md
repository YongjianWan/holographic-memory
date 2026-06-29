# HRR Bank Resharding

- generated_at: 2026-06-27T19:30:12
- dry_run: False
- db: `C:\Users\sdses\AppData\Local\hermes\memory_store.db`
- backup: `C:\Users\sdses\Desktop\随机小项目\holographic\reports\live_backups\memory_store_before_hrr_resharding_20260627_193011.db`
- categories_rebuilt: general, personal, project, user_pref

| stage | bank_count | max_fact_count | max_snr | banks_over_capacity |
|---|---:|---:|---:|---:|
| before | 4 | 2083 | 0.701 | 1 |
| after | 24 | 256 | 2.0 | 0 |

## Top banks after

| bank_name | fact_count | snr |
|---|---:|---:|
| cat:project|doc:6|shard:00 | 256 | 2.0 |
| cat:project|doc:21|shard:00 | 247 | 2.036 |
| cat:project|doc:1|shard:00 | 227 | 2.124 |
| cat:project|doc:8|shard:00 | 218 | 2.167 |
| cat:project|doc:25|shard:00 | 208 | 2.219 |
| cat:project|doc:15|shard:00 | 130 | 2.807 |
| cat:project|doc:16|shard:00 | 117 | 2.958 |
| cat:personal|doc:9|shard:00 | 110 | 3.051 |
| cat:project|doc:18|shard:00 | 98 | 3.232 |
| cat:project|doc:22|shard:00 | 94 | 3.301 |
| cat:project|doc:17|shard:00 | 77 | 3.647 |
| cat:project|doc:4|shard:00 | 77 | 3.647 |
| cat:project|doc:20|shard:00 | 70 | 3.825 |
| cat:project|doc:19|shard:00 | 66 | 3.939 |
| cat:project|doc:3|shard:00 | 47 | 4.668 |
| cat:project|doc:5|shard:00 | 46 | 4.718 |
| cat:project|doc:23|shard:00 | 45 | 4.77 |
| cat:project|doc:none|shard:00 | 22 | 6.822 |
| cat:project|doc:24|shard:00 | 14 | 8.552 |
| cat:project|doc:7|shard:00 | 14 | 8.552 |
