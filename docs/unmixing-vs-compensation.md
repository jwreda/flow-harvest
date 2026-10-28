# Unmixing vs Compensation in Flow Cytometry

This document explains the distinction between spectral unmixing and traditional compensation, how they relate to each other in spectral flow cytometry workflows, and how Flow Harvest handles both.

## Overview

| Concept | Where Applied | Purpose | Output |
|---------|--------------|---------|--------|
| **Spectral Unmixing** | On instrument (e.g., Aurora) | Separate overlapping fluorophore spectra using OLS | "Unmixed" FCS files |
| **Compensation** | In analysis software (FlowJo) | Correct residual spillover between channels | Compensation matrix in WSP |

## Spectral Unmixing

Spectral unmixing is performed on spectral flow cytometers (e.g., Cytek Aurora) during or immediately after acquisition. It uses the full emission spectrum of each fluorophore to mathematically separate signals.

**Key characteristics:**
- Uses Ordinary Least Squares (OLS) regression
- Considers the entire emission spectrum, not just peak detectors
- Performed on the instrument's software
- Results are exported as "Unmixed" FCS files
- Cannot be reproduced or modified in downstream analysis software

**When you have Unmixed data:**
- The FCS files in your `/Unmixed/` folder contain spectrally unmixed event data
- The channel names typically include fluorophore names (e.g., "BV421-A", "PE-Cy7-A")
- This is your primary data source for analysis

## Traditional Compensation

Compensation is a mathematical correction for spectral spillover between fluorophores. In traditional (non-spectral) flow cytometry, it's the primary method for correcting fluorophore overlap.

**Key characteristics:**
- Uses a spillover matrix (N×N for N fluorophores)
- Corrects for emission of one fluorophore detected in another's channel
- Can be defined and modified in analysis software like FlowJo
- Stored in the WSP file and/or FCS file metadata (`$SPILL` keyword)

**Spillover matrix example:**
```
         BV421   PE    APC
BV421    1.00   0.02  0.01
PE       0.05   1.00  0.03
APC      0.00   0.02  1.00
```

Diagonal values are always 1.0. Off-diagonal values represent spillover percentages.

## Spectral Flow: Unmixing + Compensation

For many spectral flow cytometry experiments, both processes are used:

1. **Unmixing on instrument**: Data is spectrally unmixed on the Aurora
2. **Compensation in FlowJo**: Additional compensation may be applied to correct residual spillover

This is common because:
- Unmixing may not perfectly separate all fluorophores
- Autofluorescence can introduce artifacts
- Fine-tuning in FlowJo allows optimization without re-acquiring data

**Workflow:**
```
Raw acquisition → Spectral Unmixing (Aurora) → Unmixed FCS files
                                                      ↓
                         FlowJo WSP (gates + optional compensation)
                                                      ↓
                                              Analysis results
```

## Flow Harvest Handling

### FCS File Selection (Processing Level)

When loading a workspace, Flow Harvest identifies FCS files by their directory location:

| Directory Pattern | Processing Level | Description |
|-------------------|------------------|-------------|
| `/Unmixed/` | Unmixed | Spectrally unmixed data (preferred) |
| `/Compensated/` | Compensated | Pre-compensated data |
| `/Raw/` | Raw | Unprocessed data |

**Default behavior:** Flow Harvest prefers Unmixed files when available.

### Compensation from WSP

Flow Harvest extracts compensation information from the WSP file:

1. **Global matrices**: Compensation matrices defined at the workspace level
2. **Per-sample assignments**: Which matrix is assigned to each sample
3. **Matrix colors**: Display colors from FlowJo for visual identification

### Status Indicators

In the sample list, compensation status is shown with colored dots:

| Indicator | Meaning |
|-----------|---------|
| Colored dot (cyan, red, etc.) | Compensation matrix assigned (color matches FlowJo) |
| Gray dot | No compensation assigned (normal for pure unmixed data) |
| Red X | Error reading compensation |

### When Compensation is "Missing"

For unmixed data without additional compensation in FlowJo, showing "missing" compensation is misleading. The data is valid—it simply doesn't need further compensation.

Flow Harvest distinguishes between:
- **No compensation**: Sample has no matrix assigned (valid state)
- **Compensation error**: Could not read expected compensation (problem state)

## Common Scenarios

### Scenario 1: Pure Unmixed Data
- FCS files are in `/Unmixed/` folder
- WSP contains gates but no compensation matrices
- Flow Harvest shows gray dots (no compensation needed)

### Scenario 2: Unmixed + Compensation
- FCS files are in `/Unmixed/` folder
- WSP contains compensation matrix(es)
- Flow Harvest shows colored dots matching FlowJo matrix colors

### Scenario 3: Multiple Compensation Matrices
- Different samples may use different compensation matrices
- Flow Harvest uses per-sample WSP assignments
- Color-coded dots help identify which samples use which matrix

## Technical Reference

### FlowKit API

```python
# Get compensation matrix for a sample
matrix = workspace.get_comp_matrix(sample_id)

# Get compensated events
events = sample.get_events(source='comp')

# Get raw events
events = sample.get_events(source='raw')
```

### WSP Structure

Compensation matrices in WSP files are stored as:
```xml
<transforms:spilloverMatrix
    name="Compensation-copy"
    color="#00ccff"
    transforms:id="c41dea62-..."
    spectral="1">
    <!-- matrix data -->
</transforms:spilloverMatrix>
```

Each sample references its assigned matrix by the `transforms:id` UUID.
