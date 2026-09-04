# ftt — Fine-Tuned Team

Role-tuned small models for PMOS agent teams. Wedge: a QLoRA-distilled
8B planner that matches an open-weight big-model teacher on real PMOS planning tasks,
judged blind-pairwise. Local GGUF artifact for end users; near-zero run cost.

Status: design locked (see docs/), T2/T3 in progress.

- Design doc: docs/design-2026-09-04.md
- Test plan: docs/eng-review-test-plan-2026-09-04.md
- Layout: tasks/ (inventory, mining, split, synthetic gen), harness/ (blind pairwise judge,
  gates), teacher/ (trace sampling), train/ (Kaggle QLoRA), release/ (GGUF export), fixtures/ (frozen eval set), tests/ (harness self-tests).
