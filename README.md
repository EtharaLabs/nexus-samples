<p align="center"><img src="images/hero.svg" alt="nexus" width="720"></p>

# nexus: samples

<p align="center"><b>The samples lane: 2 of 30 Harbor task bundles.</b></p>

<p align="center"><a href="#summary"><img src="https://img.shields.io/badge/bundles-2_of_30-845EF7" alt="bundles: 2 of 30"></a> <a href="#evidence-status"><img src="https://img.shields.io/badge/sealed-0-845EF7" alt="sealed: 0"></a> <a href="#difficulty-tiers"><img src="https://img.shields.io/badge/difficulty-measured-845EF7" alt="difficulty: measured"></a></p>

<p align="center"><sub><a href="#abstract">Abstract</a> | <a href="#summary">Summary</a> | <a href="#difficulty-tiers">Difficulty tiers</a> | <a href="#evidence-status">Evidence status</a> | <a href="#coverage">Coverage</a> | <a href="#dataset-structure">Dataset structure</a> | <a href="#verification-and-quality-assurance">Verification and quality assurance</a> | <a href="#reproduction">Reproduction</a> | <a href="#cite">Cite</a> | <a href="#license">License</a> | <a href="#contact">Contact</a></sub></p>

## Abstract

The curated lane of this corpus: at most 30 Harbor task bundles, every anchor seated first and every other bundle in seal order. Bundles past that ceiling live in `delivery/`.

Each bundle is one Harbor task in a directory named by its content-derived uuid5, so the name doubles as an integrity check. This page is rendered from the resident bundles on every reconcile; a value a bundle does not carry reads `absent`, and the page never fills one in.

## Summary

| Property | Value |
| --- | --- |
| Bundles | 2 of 30 |
| Sealed | 0 of 2 |
| Registrations | unregistered (2) |
| Audit verdicts | none (2) |
| Harbor schema | 1.4 (2) |

## Difficulty tiers

Difficulty is measured by the signed pilot alone and never declared in a bundle, so this page states no tier a bundle claims.

## Evidence status

The verdict is the audit outcome recorded at the sealed digest, and `none` means no verdict has landed for that digest yet. Only an authoring run removes a bundle from this lane, so removal waits for the next one.

| uuid | Verdict | Sealed digest | Stream |
| --- | --- | --- | --- |
| 136de480-2df4-5b30-8686-685cbc5749d7 | none | absent | none |
| 8263dbf4-358b-52b2-8ff0-2b26ffcafa67 | none | absent | none |

## Coverage

| Keyword | Bundles |
| --- | --- |
| cppr | 1 |
| crash-recovery | 1 |
| digital-design | 1 |
| eda | 1 |
| exactly-once | 1 |
| latch-time-borrowing | 1 |
| liberty | 1 |
| nldm | 1 |
| ocv | 1 |
| parsing | 1 |
| python | 1 |
| retraction | 1 |
| sdc | 1 |
| session-window | 1 |
| static-timing-analysis | 1 |
| streaming | 1 |
| watermark | 1 |

## Dataset structure

| Bundle | Task | Keywords | Registration | Sealed at | Tier |
| --- | --- | --- | --- | --- | --- |
| [`136de480-2df4-5b30-8686-685cbc5749d7`](136de480-2df4-5b30-8686-685cbc5749d7/) | `ethara/nldm-static-timing-136de480` | cppr, digital-design, eda, latch-time-borrowing, liberty, nldm, ocv, parsing, sdc, static-timing-analysis | unregistered | unsealed | - |
| [`8263dbf4-358b-52b2-8ff0-2b26ffcafa67`](8263dbf4-358b-52b2-8ff0-2b26ffcafa67/) | `dhawal-bathre/stream-session-window-exactly-once` | crash-recovery, exactly-once, python, retraction, session-window, streaming, watermark | unregistered | unsealed | - |

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#131a33","primaryTextColor":"#e8ecff","primaryBorderColor":"#845EF7","lineColor":"#22d3ee","fontFamily":"monospace"}}}%%
flowchart LR
    bundle["&lt;uuid&gt;/"]
    bundle --> n0["task.toml<br/>runner manifest"]
    bundle --> n1["instruction.md<br/>objective the agent reads"]
    bundle --> n2["environment/<br/>agent sandbox image"]
    bundle --> n3["tests/<br/>verifier, hidden from the agent"]
    bundle --> n4["solution/<br/>private oracle"]
    bundle --> n5["README.md"]
    bundle --> n6["trajectories/"]
```

```mermaid
%%{init: {"theme":"base","themeVariables":{"primaryColor":"#131a33","primaryTextColor":"#e8ecff","primaryBorderColor":"#845EF7","lineColor":"#22d3ee","fontFamily":"monospace"}}}%%
flowchart LR
    staging["staging/"]
    staging --> samples["samples/<br/>2 of 30"]
    samples --> delivery["delivery/<br/>0 of 10000"]
    delivery --> stock["stock/<br/>0 of 10000"]
```

## Verification and quality assurance

Each bundle's signed provenance carrier holds its screening roots, screening instant, and absolute expiry. Placement moves that carrier into the private derivation set, which this page never reads, so reconcile lists no root it cannot verify here.

## Reproduction

Each bundle directory is a complete Harbor task: `task.toml` is the runner manifest, `instruction.md` the objective, `environment/` the sandbox image, and `tests/` the verifier. Point a Harbor runner at one bundle directory to reproduce it; `solution/` stays private.

## Cite

A citation for nexus will be published here once it releases its first evidence-backed dataset. The grounding benchmark it builds on is Terminal-Bench.

```bibtex
@misc{terminalbench2026,
  title        = {Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces},
  author       = {Merrill, Mike A. and Shaw, Alexander G. and Carlini, Nicholas and others},
  year         = {2026},
  eprint       = {2601.11868},
  archivePrefix= {arXiv},
  url          = {https://arxiv.org/abs/2601.11868}
}
```

## License

See [LICENSE](LICENSE) for the terms under which this repository is published.

## Contact

[Ethara AI on GitHub](https://github.com/Ethara-Ai), [SECURITY.md](SECURITY.md) for a private report, and [CONTRIBUTING.md](CONTRIBUTING.md) for the contribution route.

Copyright (c) 2026 Green Rider Technology LLP (Ethara AI). All rights reserved.
