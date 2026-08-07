# Held-out human calibration

Run this before target-model trials with a seed not used for design inspection.
The participant must not inspect parent directories or verifier artifacts and must
use only `retrieve.py search` and `retrieve.py read` for corpus access.

```bash
cd tasks/t10_bounded_scoped_retrieval
python3 gen_env.py --seed 20260899 --out /tmp/t10-human/workspace
cd /tmp/t10-human/workspace
```

Give the participant the rendered `task.yaml` prompt with the generated topic.
Record start/end time, search calls, read calls, answer, citations, and whether any
rule was unclear. The calibration passes only if the exact answer and citation pass
`verify.py` within 60 minutes and within 8 searches/12 reads/top-5. The task author
must not count the reference workflow used during implementation as this baseline.
