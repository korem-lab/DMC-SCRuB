"""Plain-language messages for errors raised while loading Metadata files."""

from __future__ import annotations

from pandas.errors import EmptyDataError, ParserError


def metadata_error_message(error: Exception) -> str:
    """Return one actionable, non-technical message for a Metadata load error."""
    detail = str(error)

    if detail == "The Sample file or Metadata file contains an empty Sample ID.":
        return (
            "The Sample file or Metadata file contains an empty Sample ID. Please "
            "provide a name for every sample and select the corrected files again."
        )
    if isinstance(error, EmptyDataError):
        return (
            "The selected Metadata file is empty or cannot be read. Please select a "
            "valid Metadata CSV file containing column headers and sample records."
        )
    if detail == "Metadata table is empty.":
        return (
            "The Metadata file does not contain any sample records. Please add the "
            "required sample information and try again."
        )
    if detail.startswith(
        ("Metadata is missing selected columns:", "Metadata is missing required columns:")
    ):
        return (
            "The Metadata file does not contain the selected columns. Please confirm "
            "that the file is a valid CSV and select the appropriate Sample, Control, "
            "and Control Group columns again."
        )
    if detail.startswith("Metadata is missing rows for count table IDs:"):
        return (
            "Some samples in the Sample file are missing from the Metadata file. "
            "Please make sure both files contain matching sample names."
        )
    if isinstance(error, UnicodeError):
        return (
            "The Metadata file could not be read correctly. Please save it as a UTF-8 "
            "CSV file and try again."
        )
    if isinstance(error, PermissionError):
        return (
            "The Metadata file cannot be accessed. Please check the file permissions "
            "or move it to an accessible folder and select it again."
        )
    if isinstance(error, FileNotFoundError):
        return (
            "The selected Metadata file can no longer be found. Please confirm that "
            "the file still exists and select it again."
        )
    if isinstance(error, ParserError):
        return (
            "The Metadata file has an invalid or inconsistent CSV structure. Please "
            "check that every row has the same number of columns and export the file "
            "as CSV again."
        )
    return (
        "The selected Metadata file could not be loaded. Please confirm that it is a "
        "valid Metadata CSV file and try again."
    )
