# Flow Harvest

Export frequencies and MFIs from FlowJo workspaces into tidy tables, fast and without crashes.

Flow Harvest opens a FlowJo workspace (.wsp) and its .fcs files and exports the frequencies and MFIs you choose as one tidy table, ready for R, Python, Prism or AI-assisted analysis. You keep gating where you already do it. Flow Harvest handles getting the numbers out.

<!-- demo video or GIF goes here -->

> **Status:** in active use for thesis research; first public release. Validated against FlowJo on a 19-sample spectral experiment (see below).

---

## Why it exists

FlowJo kept crashing, for me and for my collaborator Colleen. That slowed us down, and it also made us dread our own work, because getting data out of FlowJo was going to be agonizing every time. Both of us need to move through our datasets quickly to keep making progress.

The problem is worst for in vivo spectral flow cytometry. Every cell carries a lot of data, and there are a lot of cells: Colleen's experiments have millions of cells per sample, and FlowJo still crashes regularly on her new computer.

Exporting statistics was the other bottleneck. In FlowJo, each relative frequency and each form of MFI takes many clicks, repeated for every gate. Copying statistics between gates is supposed to help, but it often doesn't work: the statistics don't calculate in the table, it's unclear why, and it takes a lot of troubleshooting.

## What it does

1. **Open a workspace.** Pick a .wsp file. If Flow Harvest finds the matching .fcs files, it lists the samples.
2. **Choose settings.** Pick the compensation matrix and other options, then load the data.
3. **Pick frequencies.** Choose gates from the gating hierarchy. Mark any gate as an **anchor** to normalize everything beneath it, for example frequency of live, frequency of T cells, or memory T cells as a percentage of total T cells. In FlowJo that's many clicks per population; here it's one checkbox, applied automatically to every relevant frequency underneath.
4. **Pick MFIs in the gate × marker matrix.** Every row is a gate in the workspace and every column is a stained marker. Check cells one at a time or drag a rectangle to select many. Then choose median, mean, geometric mean, or any combination.
5. **Export.** You get one tidy table with everything you selected, in the same spirit as FlowJo's table export.

The part I'm proudest of is the ergonomics: relative frequencies and MFIs are now quick to set up instead of tedious. I have my own flow experiment coming up in a couple of months, and I'm excited to use it. I think it's beautiful and functional.

## Validated against FlowJo

We compared every frequency and MFI from one spectral experiment (19 samples) exported by FlowJo and by Flow Harvest from the same workspace and files.

- **253 measurements** compared: 215 population frequencies and 38 mean or median MFIs
- **234 of 253** agree at r ≥ 0.99, and 191 at r ≥ 0.999
- **2 real disagreements**, both in one rare population (as few as 26 events in a sample). They come from small gate sizes plus negative values after spectral unmixing: FlowJo computes statistics in its display space, while Flow Harvest computes on the raw values. In response, Flow Harvest now warns when a gate has fewer than 10 events and explains when a geometric MFI can't be computed.

Before the scripted comparison, we also spot-checked by hand: exporting measurements from both tools, graphing them by group, and confirming that the rank order of mice was consistent for a given parameter.

The codebase has 262 automated tests.

## How it was built

I built Flow Harvest by directing Claude Code. I did not edit the code files myself. I described in detail what features we needed, what mattered to us, and what needed to be tested, then checked and tested each version. When a build was ready enough to be worth Colleen's time, I pushed it, she reinstalled and tried it on her data, and we iterated.

We knew from the start which functions the software had to perform, so most of the work was steady progress toward that and solving design problems along the way. Three examples:

- **Interface design.** Claude could produce an interface, but it felt strange to use: buttons in odd places, never enough negative space. I steered the layout until it was something I'd want to use.
- **Compensation matrices.** At first the app failed to find compensation matrices. Then it found them but didn't apply them, or showed them in a way that didn't match FlowJo. We ended up pulling cues from the FlowJo file itself, including the icon color assigned to each matrix, so users can see at a glance that they picked the right matrix and that the app found what was actually stored. Those cases are covered by tests.
- **Remote debugging and speed.** The app crashed on Colleen's computer, and we're not in the same place. We built out logging so she could send me error logs as she worked, which sped up development a lot. Early versions also took multiple minutes per sample. With 30-mouse experiments, that meant an hour just to export, which defeats the purpose, so we made it faster. Colleen now routinely exports experiments of 10 to 20 samples, and even her largest, 60 samples with large files, takes about 20 minutes at most.

Tools: Claude Code, mostly with Claude Opus 4.5 and Opus 4.6 (January to March 2026). All design decisions, testing and validation were done by people, and every change was reviewed by me before Colleen used it.

## Install and run

Requires Python 3.9+ (3.11 recommended).

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

## Acknowledgments

The idea of using FlowKit to pull statistics out of FlowJo workspaces through a simple GUI came from **Lorenzo Netti**, who built earlier, simpler tools along those lines. Flow Harvest was developed independently, but it started from his insight.

## Citation

If you use Flow Harvest in your research, please cite it using the "Cite this repository" button on GitHub (from `CITATION.cff`).

## License

GPL-3.0-or-later, because the interface uses PyQt5 (GPL v3). We plan to move to PySide6 (LGPL) and relicense under MIT.

## Roadmap

- Port the interface to PySide6 / Qt 6
- Public example data so anyone can try it and run the full test suite
