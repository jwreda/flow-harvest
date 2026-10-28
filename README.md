# Flow Harvest

Export frequencies and MFIs from FlowJo workspaces into tidy tables, fast, even for large spectral experiments.

Flow Harvest opens a FlowJo workspace (.wsp) and its .fcs files and exports the frequencies and MFIs you choose to an Excel file, with everything you selected in one tidy table, ready for R, Python, Prism or AI-assisted analysis. You keep gating where you already do it. Flow Harvest handles getting the numbers out.

> **Status:** in active use for thesis research; first public release. Validated against FlowJo on a 19-sample spectral experiment (see below).

---

## Why it exists

FlowJo kept crashing, for me and for my collaborator Colleen. That slowed us down, and it also made us dread our own work, because getting data out of FlowJo was going to be agonizing every time. Both of us need to move through our datasets quickly to keep making progress.

The problem is worst for in vivo spectral flow cytometry. Every cell carries a lot of data, and there are a lot of cells: Colleen's experiments have millions of cells per sample, and FlowJo still crashes regularly on her new computer.

Exporting statistics was the other bottleneck. In FlowJo, each relative frequency and each form of MFI takes many clicks, repeated for every gate. Copying statistics between gates is supposed to help, but it often doesn't work: the statistics don't calculate in the table, it's unclear why, and it takes a lot of troubleshooting.

## What it does

1. **Open a workspace.** Pick a .wsp file. If Flow Harvest finds the matching .fcs files, it lists the samples.
2. **Choose settings.** Pick the compensation matrix and other options, then load the data.
3. **Pick frequencies.** Choose gates from the gating hierarchy. Mark any gate as a **reference gate** to normalize everything beneath it, for example frequency of live, frequency of T cells, or memory T cells as a percentage of total T cells. In FlowJo that's many clicks per population; here it's one checkbox, applied automatically to every relevant frequency underneath.
4. **Pick MFIs in the gate × marker matrix.** Every row is a gate in the workspace and every column is a stained marker. Check cells one at a time, drag across cells to check many, or Shift+drag to select a rectangle. Then choose median, mean, geometric mean, or any combination.
5. **Export.** You get an Excel file. One sheet has everything you selected in a single table, one row per sample, in the same spirit as FlowJo's table export. Other sheets break out counts, frequencies, MFIs, keywords and the gating strategy.

The part I'm proudest of is the ergonomics: relative frequencies and MFIs are now quick to set up instead of tedious. I have my own flow experiment coming up in a couple of months, and I'm excited to use it. I think it's beautiful and functional.

## Validated against FlowJo

We compared the frequencies and the mean and median MFIs from one spectral experiment (19 samples), exported by FlowJo and by Flow Harvest from the same workspace and files. Geometric MFI was not part of this comparison.

- **253 measurements** compared: 215 population frequencies and 38 mean or median MFIs
- **234 of 253** track FlowJo at r ≥ 0.99 (Pearson correlation across the 19 samples), and 191 of the 250 where r can be computed reach r ≥ 0.999. Correlation shows the two tools rise and fall together; it is not the same as exact agreement. Full breakdown in [docs/VALIDATION.md](docs/VALIDATION.md).
- **2 clear disagreements** (r below 0.90), both in one rare population (as few as 26 events in a sample). The mean Ki67 difference comes from a small gate with many negative values after spectral unmixing: FlowJo computes statistics in its display space, and Flow Harvest computes on the linear values. The frequency difference is a few cells in a tiny gate. We suspect cells sitting on the gate edge, but we have not confirmed it. In response, Flow Harvest now lists gates with fewer than 10 events on a Warnings sheet in the export, and warns you, when you turn on geometric MFI, that it can't be computed for populations with negative values.

Before the scripted comparison, we also spot-checked by hand: exporting measurements from both tools, graphing them by group, and confirming that the rank order of mice was consistent for a given parameter.

Digging into this also taught us things about FlowJo that are documented but easy to miss, such as that its statistics come from events binned in display space.

267 automated tests: 258 pass, and 9 are skipped until example data is public.

## How it was built

I built Flow Harvest by directing Claude Code. I did not edit the code files myself. I described in detail what features we needed, what mattered to us, and what needed to be tested, then checked and tested each version. When a build was ready enough to be worth Colleen's time, I pushed it, she reinstalled and tried it on her data, and we iterated.

We knew from the start which functions the software had to perform, so most of the work was steady progress toward that and solving design problems along the way. Three examples:

- **Interface design.** Claude could produce an interface, but it felt strange to use: buttons in odd places, never enough negative space. I steered the layout until it was something I'd want to use.
- **Compensation matrices.** At first the app failed to find compensation matrices. Then it found them but didn't apply them, or showed them in a way that didn't match FlowJo. We ended up pulling cues from the FlowJo file itself, including the icon color assigned to each matrix, so users can see at a glance that they picked the right matrix and that the app found what was actually stored.
- **Remote debugging and speed.** The app crashed on Colleen's computer, and we're not in the same place. We built out logging so she could send me error logs as she worked, which sped up development a lot. Early versions also took multiple minutes per sample. With 30-mouse experiments, that meant an hour just to export, which defeats the purpose, so we made it faster. Colleen now routinely exports experiments of 10 to 20 samples, and even her largest, 60 samples with large files, takes about 20 minutes at most.

Tools: Claude Code, mostly with Claude Opus 4.5 and Opus 4.6 (January to March 2026, with fixes since). We collaborated with Claude. We were firm on what the design had to accomplish and asked it to follow best practices. We decided what the tests had to check, and Claude wrote them. The tests were not enough on their own. They would often pass while the actual use failed, likely because our files were larger, messier and had more surprising properties than the test data, and we often saw crashes from runaway processes that the tests did not catch. So we tested every build thoroughly on real data, even when Claude was confident it would work. I tested every change before Colleen used it.

## Install and run

Requires Python 3.10+ (3.11 recommended).

```bash
git clone https://github.com/jwreda/flow-harvest.git
cd flow-harvest
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -e .
python -m flowkit_gui.main
```

Run the tests with `pip install -e ".[dev]"` then `pytest`. Some tests need example data and are skipped without it.

Flow Harvest is built on [FlowKit](https://github.com/whitebeardlabs/flowkit), which does the workspace parsing and gating. For the code structure and design decisions, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Contributors

- **Joe Reda** ([ORCID 0000-0002-9413-5111](https://orcid.org/0000-0002-9413-5111)) — design, development direction, validation
- **Colleen Foley**, Pritzker School of Molecular Engineering, University of Chicago ([ORCID 0009-0002-1636-7205](https://orcid.org/0009-0002-1636-7205)) — co-design, primary research user, validation

## Citation

If you use Flow Harvest in your research, please cite it using the "Cite this repository" button on GitHub (from `CITATION.cff`).

## License

GPL-3.0-or-later, because the interface uses PyQt5 (GPL v3). We plan to move to PySide6 (LGPL) and relicense under MIT.

## Roadmap

- Port the interface to PySide6 / Qt 6
- Public example data so anyone can try it and run the full test suite
