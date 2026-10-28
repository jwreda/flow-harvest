# Validation against FlowJo

We exported every population frequency and MFI from one spectral flow cytometry experiment (19 samples) twice: once from FlowJo, and once from Flow Harvest, using the same .wsp workspace and .fcs files. We then compared the two exports measurement by measurement across the 19 samples. This page reports aggregate results only: no sample names, gate paths or event-level data.

## Summary

| | |
|---|---|
| Measurements compared, each across 19 samples | 253 |
| Pearson r ≥ 0.99 | 234 (92%) |
| Pearson r ≥ 0.999 (of 250 where r is defined) | 191 |
| Real disagreements | 2, both in one rare population |

Pearson r tells you whether the two tools rise and fall together across samples. It is not the same as exact agreement, so the comparison script also records the mean difference, the absolute difference and the RMSE for every measurement.

## By measurement type

Tiers are assigned by r: Excellent ≥ 0.99, Good 0.95–0.99, Acceptable 0.90–0.95, Concerning < 0.90. "Identical" means both tools gave exactly the same value in every sample, so r cannot be computed.

| Measurement | n | Median r | Excellent | Good | Acceptable | Concerning | Identical |
|---|---:|---:|---:|---:|---:|---:|---:|
| Frequency of live | 74 | 0.99996 | 70 | 2 | 1 | 0 | 1 |
| Frequency of CD45+ | 71 | 0.99996 | 67 | 2 | 1 | 0 | 1 |
| Frequency of parent | 70 | 0.99977 | 68 | 0 | 0 | 1 | 1 |
| Median MFI | 19 | 0.99875 | 14 | 3 | 2 | 0 | 0 |
| Mean MFI | 19 | 0.99835 | 15 | 1 | 2 | 1 | 0 |

The 215 frequencies are about 72 populations, each expressed against three denominators (of live, of CD45+, of parent). That exercises Flow Harvest's anchor feature, but they are not 215 independent populations.

## The 19 below r = 0.99

| Tier | Count | What they are |
|---|---:|---|
| Identical | 3 | One near-empty T cell subset, under three frequency denominators. Zero difference in every sample. |
| Concerning | 2 | One rare non-immune population: its frequency (r = 0.87, mean difference +0.31 percentage points) and its mean Ki67 (r = 0.72). |
| Acceptable | 6 | Mostly mean or median MFIs (Ki67, PD1, granzyme B) in small gates, plus two frequencies of a very rare subset (mean difference under 0.001 points). |
| Good | 8 | MFIs and frequencies in small lymphocyte gates. |

The comparison script flags 5 measurements as "Concerning". Three of them are the Identical cases above, where a correlation cannot be computed on a constant. That leaves two real disagreements.

## Why they differ, and what changed

- **Small gates.** The rare population had a median of 181 events per sample, and as few as 26. The smallest T cell gates held 0 to 4 events in six samples. At those counts, a handful of cells moves a mean.
- **Negative values after spectral unmixing.** 28–49% of Ki67 events were negative in every sample, which is typical for spectral data. FlowJo computes statistics in its biexponential display space; Flow Harvest computes on the raw linear values. Both are defensible, and they diverge most when many values sit below zero. This explains the Ki67 difference.
- **The frequency difference.** <!-- PENDING JOE: mechanism for the r = 0.87 frequency miss, or "we have not pinned down why" -->
- **Not compensation.** The one sample flagged as an outlier (z = 2.58) used the same compensation matrix as the other 18. Its differences sat in the same tiny gates.
- **What we built in response.** Flow Harvest now warns on gates under 10 events ("statistics are unreliable"), notes gates under 50, and explains when a geometric MFI can't be computed instead of returning a blank.

## Method

An R script pairs each FlowJo export column with its Flow Harvest counterpart, computes Pearson r, mean and absolute differences and RMSE across samples, and assigns tiers by r. Before the scripted comparison, we spot-checked by hand: exporting measurements from both tools, graphing them by group, and confirming that the rank order of mice was consistent for a given parameter.

The comparison data come from Colleen Foley's thesis research and are not public. The comparison script and the software were written with Claude Code; Joe Reda and Colleen Foley set what had to be compared, reviewed the results and investigated the disagreements.
