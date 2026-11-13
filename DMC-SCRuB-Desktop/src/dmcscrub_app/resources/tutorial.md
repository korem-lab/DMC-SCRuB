# C-SCRuB and DMC-SCRuB Tutorial

This guide explains how to prepare input files, run C-SCRuB or DMC-SCRuB,
download the results, and review previous runs.

## Preparation

### 1: Prepare the Input Files

Prepare two separate CSV files: one Count Table and one Metadata Table.

#### Count Table

Use one row for each sample.

Use the first column for the sample name. Every sample name must be unique and
non-empty.

Use each remaining column for one taxon. A taxon can be an ASV, species, or
another feature in your analysis. Every taxon column name must be unique and
non-empty.

Enter numeric read counts only. Values must be finite and non-negative. Every
row must contain the same number of columns as the header.

#### Metadata Table

Use one row for each sample in the Count Table.

The metadata must contain:

- A **sample name column** whose values match the first column of the Count
  Table.
- A **concentration column** containing a non-negative numeric concentration
  for each sample.

DMC-SCRuB also requires:

- A **batch column** identifying the experimental batch of each sample.
- A **label column** containing the outcome to predict.
- One **positive value** from the label column. The selected value is treated
  as `1`; all other values are treated as `0`.

You may use any column names. You will select the correct columns when loading
the dataset.

Sample names must be unique and non-empty. C-SCRuB requires at least two
samples and two distinct concentration values. DMC-SCRuB requires at least two
batches and both positive and negative training samples.

### 2: Load a Dataset

Select **Upload** in the top toolbar or select the **+** beside the tabs, then
choose **C-SCRuB** or **DMC-SCRuB**.

Select the Count Table and Metadata Table. Give the dataset a name.

In **Column Mapping**, select:

- The metadata column containing sample names.
- The metadata column containing concentration values.
- For DMC-SCRuB, the batch column and label column.
- For DMC-SCRuB, the label value that should be treated as positive.

Each selected metadata column must be different.

Select **Open Dataset**.

---

## Run the Software

### 3: Understand the Workspace

The workspace has three main areas:

- **Input Summary** shows the selected files and basic dataset statistics.
- **Workflow Diagram** shows the samples included in the run.
- The right-side **Concentration Color Table** lists each sample and its
  concentration. Higher and lower concentrations use different colors. The Run
  button for the selected algorithm is at the bottom of this panel.

Use **Find** in the Input Summary to locate a sample or workflow item. The
matching route or node is highlighted in the Workflow Diagram.

### 4: Check the Inputs

Before starting, confirm that:

- Count Table and Metadata Table sample names match.
- Read counts and concentration values are numeric, finite, and non-negative.
- The dataset contains at least two samples.
- The concentration column contains at least two distinct values.
- For DMC-SCRuB, the batch and label selections are correct and the training
  data contains both the positive and negative classes.

If the app finds repairable cells, it shows an **Invalid Input Values** dialog.
Select **Run Anyway** to replace those invalid values with `0`, or select
**Re-enter data** to return without starting a run.

The files on disk are never modified.

### 5: Run the Analysis

Select **Run C-SCRuB** or **Run DMC-SCRuB**.

For DMC-SCRuB, the last batch in the aligned metadata is held out as the test
batch. The other batches are used for training with the selected positive
label value.

The Result panel shows the current stage, elapsed time, and run notes:

1. Reading the input tables.
2. Preparing aligned inputs.
3. Fitting the selected algorithm.
4. Writing the result.

Select **Cancel** to stop the active run. Only one analysis can run at a time,
but you can continue viewing other tabs.

---

## Download Results

### 6: Download the Result

A successful C-SCRuB or DMC-SCRuB run produces:

- **Decontaminated relative abundance** — Estimated taxon proportions after
  decontamination. Rows are samples and columns are taxa.

DMC-SCRuB also produces:

- **Prediction probabilities** — Classification probabilities for samples in
  the held-out test batch.

Select **Save file** to export the result CSV.

Select **Save all (.zip)** to export the result together with the run
configuration, manifest, and logs.

Select **Open folder** to open the run directory. Select **Open log** to inspect
the backend log.

---

## Other Features

### 7: Review Previous Runs

Select **History** to view successful, failed, and cancelled runs.

Select a successful or failed run to reopen its saved configuration and result.

Select **Delete** to choose individual runs to remove. Select **Clear** to remove
all runs shown in History. Deleted runs and result files cannot be recovered.

### 8: Navigate the App

- **Home** returns to the leftmost tab.
- **Upload** opens another dataset.
- **Reload** reads the current dataset files again.
- **History** opens previous runs.
- **Tutorial** returns to this guide.

Drag tabs to change their order. Double-click a dataset tab to rename it. Select
**×** to close a tab. Select **+** to add another dataset.
