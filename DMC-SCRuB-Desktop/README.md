# C-SCRuB Desktop

PySide6 desktop application for running C-SCRuB and DMC-SCRuB from a count
table and metadata file.

Requires Python 3.10 or newer. The macOS app build on this branch targets
macOS 12.0 or newer (Apple Silicon).

## Install

```bash
git clone <repository-url>
cd dmcscrub_app
python -m pip install .
```

## Run

```bash
cscrub-desktop
```

## Required Inputs

- Count table CSV: the first column contains unique sample IDs; remaining
  columns contain non-negative feature counts.
- Metadata CSV: choose a unique sample-ID column and a concentration column in
  the upload dialog.
- DMC-SCRuB additionally requires a batch column.

Each successful run writes `decontaminated_relative_abundance.csv` and a
manifest. On macOS, runs are stored under:

```text
~/Library/Application Support/C-SCRuB Desktop/runs/
```

Windows uses `%LOCALAPPDATA%\C-SCRuB Desktop\runs`; Linux uses
`$XDG_DATA_HOME/C-SCRuB Desktop/runs` or `~/.local/share/C-SCRuB Desktop/runs`.

C-SCRuB Desktop is released for academic non-commercial use. See `LICENSE`.
