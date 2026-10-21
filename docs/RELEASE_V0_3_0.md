# v0.3.0 local MVP

Date: 2026-10-21 (Asia/Amman). This release changes the **chatbot's
retrieval and citation handling only**. The published knowledge, the collection
and the model are unchanged.

## Install

```powershell
.\install-mvp.cmd -Version v0.3.0
```

The launcher also selects v0.3.0 when double-clicked without arguments. A Git
Hub release with the same public assets is published under
[releases/tag/v0.3.0](https://github.com/RetajMelhem/telescope-chatbot-agentic-rag/releases/tag/v0.3.0).

## What changed

Four changes, all in the request path:

1. **Identical evidence collapses to one retrieval slot.** The site footer
   contact block is admitted 54 times on English pages and 53 times on Arabic
   pages. Those occurrences share one vector and one score, so they consumed
   whole retrieval slots and made the citation land on whichever page the
   database happened to return first. Identical occurrences now collapse to one
   representative, chosen without a model and without a similarity score, and
   the freed slots are refilled with different evidence. Every occurrence stays
   in the corpus and in the evidence-group inventory.
2. **An unrestricted search reads the corpus in the answer's language.** The
   planner may still restrict a search to a page, owner or source type, and
   every explicit restriction is untouched. A search with no restriction now
   reads the bilingual corpus in the language the answer will be written in.
3. **The candidate budget was retuned.** Top-k 11, BM25 rescue 2, ancestor
   context 1, which leaves eight dense candidates after the collapse and keeps
   the same total pool.
4. **The writer cites a short reference instead of a long identifier.** The
   writer was given the 64-character hexadecimal chunk identifier of every
   eligible source and told to copy it exactly. One wrong character invalidated
   the whole reply, after the provider call had already succeeded. The writer
   now receives a short reference that is resolved back to the real chunk
   identifier before validation. A real identifier is still accepted, and
   either form must resolve inside that part's eligible evidence, so a citation
   outside the eligible evidence still fails closed, and an unknown reference
   fails closed exactly as an unknown identifier would.

## Measured effect

Twenty approved everyday questions, the unchanged published corpus, both
builds measured with the identical corrected metric.

| Metric | v0.2.0 | v0.3.0 | change |
| --- | --- | --- | --- |
| **outright failures, no answer delivered** | 1 / 20 | **0 / 40** | **-1** |
| corpus publishes the required fact | 1.0000 | 1.0000 | 0 |
| **cited evidence carries the required fact** | 0.8889 | **0.9444** | **+0.0556** |
| answer states the fact, literal wording | 0.6111 | **0.7222** | **+0.1111** |
| **answer states the fact, paraphrase-aware** | 0.8889 | **0.9444** | **+0.0556** |
| citation number coverage | 1.0000 | 1.0000 | 0 |
| invalid citations | 0 | 0 | 0 |
| price-abstain violations | 0 | 0 | 0 |

Retrieval recall over the same questions, measured with the real
`RequestDenseRetriever` against the published corpus:

| Retrieval policy | macro fact recall | full recall | zero recall | duplicate slots |
| --- | --- | --- | --- | --- |
| v0.2.0 shipped | 0.8646 | 41 / 48 | 6 | 0.28 |
| v0.3.0 (this release) | **0.9583** | **46 / 48** | **2** | **0.00** |

The answer-level figures are means over three runs of the v0.3.0 build, because
the writer is stochastic and one question is five points. v0.3.0 produced no
failure in any of its runs. v0.2.0 failed one of its runs with
`invalid_conversational_citation`, the transcription defect that change 4
removes.

## What did not change

- The published knowledge. Knowledge identity is unchanged at
  `a16414530c40e991c3b0b506d9b30d2bac3d57587d36aa39759cafaaa56faccb`, and the
  release reuses the v0.2.0 knowledge archive and native database snapshot.
- The collection, its contents and the absence of any alias.
- The chat model. `openai/gpt-6-luna` on the pinned provider route, zero
  retries.
- The installer, the secrets handling and the read-only database key.

## Measured and not measured

The figures above are retrieval and answer-support measurements over twenty
questions. The paraphrase-aware statement check keeps the numbers and the
clinic's published vocabulary and ignores exact wording; it is a mechanical
heuristic, not an independent semantic review of the prose. A free chat
endpoint was screened and rejected because it cannot serve the pinned route or
the strict response schema, and a rebuilt corpus was measured and rejected
because the site publishes every comparison twice, so the rebuilt corpus carries
both renderings and the answer carrier is crowded out of the candidate pool. The
published corpus therefore stays, and this release changes only the request
path.

The one remaining known gap is unchanged: the site publishes its full clinic
and department index in its navigation, and the cleaner removes navigation as
repeated material, so that list is in no corpus and the question "which clinics
do you have" is not yet answerable.

## Rollback

The v0.2.0 release stays published and installable:

```powershell
.\install-mvp.cmd -Version v0.2.0
```

A code-only update needs no corpus or knowledge change, and the knowledge
assets are identical between the two releases.
