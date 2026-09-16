# ONE-FLOOR TEST PROTOCOL

## Recommended first case
- Discipline: ВК.
- Scope: horizontal water distribution on one typical residential floor.
- Inputs: stage P plan + architecture background + corresponding RD withheld + reference BOQ/takeoff if available.
- Split: entire project held out.

## Run sequence
1. Freeze hashes and model versions.
2. Stage 1 recognition from P only.
3. Freeze Stage 1 output.
4. Stage 2 generate MEP NetworkGraph.
5. Freeze Stage 2 output.
6. Derive STRICT BOQ.
7. Price using only training/history database.
8. Freeze end-to-end output.
9. Reveal RD/BOQ references.
10. Score recognition, engineering and commercial metrics separately.

## Suggested PoC gates
- Stage 1 key endpoint/anchor F1 >= 0.90.
- Stage 2 required terminal connectivity >= 0.95.
- Stage 2 topology edge F1 >= 0.85 against reference, with separate valid-alternative review.
- Generated total route length error <= 15% for PoC; target <= 8% for pilot.
- Quantity WAPE <= 15% PoC; target <= 7-10% pilot.
- BOQ line coverage >= 90% PoC; target >= 95% pilot.
- Pricing total APE <= 15% PoC on supported rows; target <= 10% pilot.
- Unresolved share must be reported, not hidden.

These are engineering gates for hypothesis testing, not universal production guarantees.
