"""Safe file readers. Uploaded content is only ever parsed as data, never executed.

Returns a ``RawTable``: columns (name -> numpy array), per-column units, and header metadata.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..config import get_settings


class IngestError(Exception):
    """A user-facing problem with an input file."""

    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass
class RawTable:
    columns: dict[str, np.ndarray]
    units: dict[str, str | None] = field(default_factory=dict)
    header: dict[str, Any] = field(default_factory=dict)
    file_format: str = "csv"            # csv | fits
    n_rows: int = 0
    notes: list[str] = field(default_factory=list)
    fits_info: dict[str, Any] = field(default_factory=dict)   # hdus, image shapes...


FITS_MAGIC = b"SIMPLE  ="


def sniff_format(path: Path) -> str:
    with open(path, "rb") as f:
        head = f.read(2048)
    if head.startswith(FITS_MAGIC):
        return "fits"
    if head.startswith(b"\x1f\x8b"):
        raise IngestError("Compressed files are not supported.",
                          "Decompress the file (e.g. .fits.gz is accepted only when named *.fits.gz) and re-upload.")
    if b"\x00" in head:
        raise IngestError("This looks like a binary file that is not FITS.",
                          "Supported formats: CSV/TXT/TSV tables and FITS files.")
    return "text"


def read_table(path: Path, filename: str | None = None) -> RawTable:
    fmt = sniff_format(path)
    if fmt == "fits":
        return _read_fits(path)
    return _read_text(path)


def _read_text(path: Path) -> RawTable:
    settings = get_settings()
    try:
        raw = path.read_bytes()
    except OSError as e:
        raise IngestError(f"Could not read file: {e}") from e
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    lines = text.splitlines()
    notes: list[str] = []
    header: dict[str, Any] = {}

    # Strip leading comment lines (#, %), keeping them as header text. A final comment line that
    # looks like a column header (common in IPAC/ascii tables) is used if no other header exists.
    comment_lines = []
    body_start = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            body_start = i + 1
            continue
        if s.startswith("#") or s.startswith("%") or s.startswith("\\"):
            comment_lines.append(s.lstrip("#%\\ ").rstrip())
            body_start = i + 1
            continue
        break
    body = lines[body_start:]
    if not body:
        raise IngestError("The file contains no data rows.")
    header["comments"] = comment_lines[:50]
    for c in comment_lines:
        low = c.lower()
        for key in ("mission", "telescope", "instrument", "object", "target", "timesys", "timeunit"):
            if low.startswith(key + ":") or low.startswith(key + "="):
                header[key] = c.split(":", 1)[-1].split("=", 1)[-1].strip()

    sample = "\n".join(body[:50])
    sep = _sniff_sep(sample)
    first = [t.strip() for t in (body[0].split(sep) if sep else body[0].split())]
    has_header = any(not _is_number(t) for t in first if t)
    try:
        df = pd.read_csv(
            io.StringIO("\n".join(body)), sep=sep if sep else r"\s+", engine="python",
            header=0 if has_header else None, nrows=settings.max_rows + 1,
            skipinitialspace=True, on_bad_lines="skip", comment=None,
        )
    except Exception as e:  # pandas raises many types for malformed input
        raise IngestError(f"Could not parse the file as a table: {e}",
                          "Check that it is a delimited text file (comma, tab, semicolon or whitespace).") from e
    if not has_header:
        # try the last comment line as header
        if comment_lines and len(comment_lines[-1].replace(",", " ").split()) == df.shape[1]:
            df.columns = comment_lines[-1].replace(",", " ").split()
            notes.append("column names taken from the last comment line")
        else:
            df.columns = [f"col{i + 1}" for i in range(df.shape[1])]
            notes.append("no header row found; columns named col1..colN")
    if len(df) > settings.max_rows:
        raise IngestError(f"File has more than {settings.max_rows:,} rows.",
                          "Bin or subset the data before uploading.")
    df.columns = [str(c).strip() for c in df.columns]
    # Units sometimes live in the header as "flux [e-/s]" or "time (days)"
    units: dict[str, str | None] = {}
    clean_cols = {}
    for c in df.columns:
        name, unit = _split_unit(c)
        units[name] = unit
        clean_cols[c] = name
    df = df.rename(columns=clean_cols)
    df = df.loc[:, ~df.columns.duplicated()]
    cols: dict[str, np.ndarray] = {}
    for c in df.columns:
        s = df[c]
        num = pd.to_numeric(s, errors="coerce")
        # keep numeric if most entries parse; otherwise keep the strings
        if num.notna().mean() >= 0.5 or s.dropna().empty:
            cols[c] = num.to_numpy(dtype=float)
        else:
            cols[c] = s.astype(str).to_numpy()
    n_dropped_dup = len(clean_cols) - len(df.columns)
    if n_dropped_dup:
        notes.append(f"{n_dropped_dup} duplicate column name(s) dropped")
    return RawTable(columns=cols, units=units, header=header, file_format="csv",
                    n_rows=len(df), notes=notes)


def _sniff_sep(sample: str) -> str | None:
    counts = {s: sample.count(s) for s in [",", "\t", ";", "|"]}
    best = max(counts, key=counts.get)
    return best if counts[best] >= max(1, len(sample.splitlines()) // 2) else None


def _is_number(tok: str) -> bool:
    try:
        float(tok)
        return True
    except ValueError:
        return False


def _split_unit(col: str) -> tuple[str, str | None]:
    import re
    m = re.match(r"^\s*(.*?)\s*[\[(]\s*([^\])]+?)\s*[\])]\s*$", col)
    if m and m.group(1):
        return m.group(1), m.group(2)
    return col.strip(), None


def _read_fits(path: Path) -> RawTable:
    from astropy.io import fits
    settings = get_settings()
    try:
        hdul = fits.open(path, memmap=True, lazy_load_hdus=True)
    except Exception as e:
        raise IngestError(f"Corrupted or unreadable FITS file: {e}",
                          "Re-download the file from the archive and try again.") from e
    try:
        info: dict[str, Any] = {"hdus": []}
        table_hdu = None
        for i, h in enumerate(hdul):
            entry = {"index": i, "name": h.name, "type": type(h).__name__}
            if isinstance(h, (fits.BinTableHDU, fits.TableHDU)):
                entry["rows"] = int(h.header.get("NAXIS2", 0))
                entry["columns"] = [str(c) for c in h.columns.names]
                if table_hdu is None and entry["rows"] > 0:
                    table_hdu = h
                # prefer an extension literally named LIGHTCURVE / the standard Kepler-TESS one
                if h.name.upper() in ("LIGHTCURVE", "FLUX", "PDCSAP_FLUX"):
                    table_hdu = h
            elif hasattr(h, "shape") and h.data is not None or getattr(h, "header", {}).get("NAXIS", 0):
                entry["shape"] = tuple(int(x) for x in h.header.get("NAXIS", 0) and
                                       [h.header.get(f"NAXIS{k}", 0) for k in range(1, int(h.header["NAXIS"]) + 1)])
            info["hdus"].append(entry)
        prim = hdul[0].header
        header = {k.lower(): _clean_header(prim.get(k)) for k in
                  ("TELESCOP", "INSTRUME", "OBJECT", "TICID", "KEPLERID", "EPIC", "SECTOR", "CAMERA",
                   "CCD", "QUARTER", "CAMPAIGN", "RA_OBJ", "DEC_OBJ", "TESSMAG", "KEPMAG", "TEFF",
                   "LOGG", "RADIUS", "ORIGIN", "PROCVER") if k in prim}
        mission = str(prim.get("TELESCOP", "")).lower()
        if "tess" in mission:
            header["mission"] = "tess"
        elif "kepler" in mission:
            header["mission"] = "kepler"
        elif "k2" in mission:
            header["mission"] = "k2"
        if table_hdu is None:
            # Image-only FITS: report structure; no table data
            return RawTable(columns={}, header=header, file_format="fits", n_rows=0, fits_info=info,
                            notes=["no binary table extension with rows; image/cube data only"])
        th = table_hdu.header
        header["extname"] = table_hdu.name
        for k in ("TIMESYS", "TIMEUNIT", "BJDREFI", "BJDREFF", "EXPOSURE", "TSTART", "TSTOP", "TIMEDEL",
                  "INT_TIME", "NUM_FRM", "CDPP0_5", "CDPP1_0", "CDPP2_0", "CROWDSAP", "FLFRCSAP", "PDCVAR"):
            if k in th:
                header[k.lower()] = _clean_header(th.get(k))
        if int(table_hdu.header.get("NAXIS2", 0)) > settings.max_rows:
            raise IngestError(f"FITS table has more than {settings.max_rows:,} rows.")
        data = table_hdu.data
        cols: dict[str, np.ndarray] = {}
        units: dict[str, str | None] = {}
        notes: list[str] = []
        for col in table_hdu.columns:
            name = str(col.name)
            arr = np.asarray(data[name])
            units[name] = str(col.unit) if col.unit else None
            if arr.ndim == 1:
                if arr.dtype.kind in "iuf":
                    arr = arr.astype(float) if name.upper() != "QUALITY" else arr.astype(np.int64)
                    cols[name] = arr
                elif arr.dtype.kind in "SUO":
                    cols[name] = arr.astype(str)
            else:
                notes.append(f"column {name} has shape {arr.shape[1:]}; not loaded as a 1-D series")
        return RawTable(columns=cols, units=units, header=header, file_format="fits",
                        n_rows=int(table_hdu.header.get("NAXIS2", 0)), notes=notes, fits_info=info)
    except IngestError:
        raise
    except Exception as e:
        raise IngestError(f"Could not interpret FITS structure: {e}") from e
    finally:
        hdul.close()


def _clean_header(v: Any) -> Any:
    if isinstance(v, (int, float, str, bool)) or v is None:
        if isinstance(v, float) and not np.isfinite(v):
            return None
        return v
    return str(v)
