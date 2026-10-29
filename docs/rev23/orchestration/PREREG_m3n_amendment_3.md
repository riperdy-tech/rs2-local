# PREREG_m3n amendment 3: C7 and C8 full-text hits must be in a reporting document (2026-10-29)

**When it was written:** before any C7 or C8 truth label existed, and before any 3N model run. C1 to C6 are already labelled and are not affected.

## The defect

The C7 and C8 full-text queries match terms that contracts *define*:
- C7 matches "withdraw" together with "guidance";
- C8 matches "event of default" together with "acceleration".

Most hits are therefore in exhibits that report nothing: credit agreements, indentures, merger agreements and incentive plans. The file types of the stored C7 and C8 hits, read from the FTS responses already held (no new request):

| File type | Hits |
|---|---|
| EX-10.1 | 2,183 |
| 10-Q | 995 |
| EX-4.1 | 813 |
| EX-10.2 | 739 |
| EX-2.1 | 513 |
| 8-K | 384 |
| EX-99.1 | 369 |
| others | … |

None of the first 12 C7 queue entries had a withdrawal sentence in its 8-K or its press-release exhibits. A draw over such a pool would label hundreds of contracts to find each real event. Every candidate would still be read; only the effort is wasted.

## The amended rule (C7 and C8 only)

An FTS candidate of C7 or C8 is kept only when at least one of its hit documents is:
- the filing's own body: file type 8-K, 8-K/A, 10-Q, 10-Q/A, 10-K or 10-K/A;
- or a press-release exhibit: EX-99.x.

Item-code candidates (C8 Item 2.04) are always kept.

| Class | Candidates before | Candidates after | Issuers after |
|---|---|---|---|
| C7 | 2,118 | 314 | 208 |
| C8 | 3,864 | 1,365 | 773 |

The rest of the draw is unchanged: one ticket per issuer (amendment 2), the same class seeds, and the same order of classes. The earlier C7 and C8 queues are kept as `m3n/queue_v1b/`.

## Why only C7 and C8

C1 to C6 have item-code channels (1.03, 4.02, 3.01, 1.01/2.01, 1.02) that put the reporting filing in the pool. Their FTS noise is harmless for completeness, and their labels were already set; redrawing them would discard completed, blind-ordered work.

The limit this leaves:
- an event of C7 or C8 disclosed **only** inside a contract exhibit is no longer a candidate;
- a guidance withdrawal or a default is reported in the body or a press release. Such a case is not expected, but it is not proven absent.

It is stated here as a limit on discovery completeness.
