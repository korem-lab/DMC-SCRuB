# DMC-SCRuB DESKTOP

PySide6 desktop application for running C-SCRuB and DMC-SCRuB from a count
table and metadata file.

Requires Python 3.10 or newer.

## Install

```bash
git clone <repository-url>
cd DMC-SCRuB
git switch DMC-SCRuB-Desktop
cd DMC-SCRuB-Desktop
python -m pip install .
```

## Run

```bash
dmcscrub-app
```

## Required Inputs

- Count table CSV: the first column contains unique sample IDs; remaining
  columns contain non-negative feature counts.
- Metadata CSV: choose a unique sample-ID column and a concentration column in
  the upload dialog.
- DMC-SCRuB additionally requires a batch column.

The C-SCRuB example files are located in the `dmc_scrub example` folder. Use
`samples.csv` as the Sample / Count Table file and `concentrations.csv` as the
Metadata Table file. In Column Mapping, select `Unnamed: 0` as the Sample name
column and `x` as the Concentration column. All example data were generated
through simulation.

Each successful run writes `decontaminated_relative_abundance.csv` and a
manifest. On macOS, runs are stored under:

```text
~/Library/Application Support/DMC-SCRuB DESKTOP/runs/
```