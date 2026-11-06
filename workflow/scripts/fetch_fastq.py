"""Download one library's FASTQ files.

ENA-hosted runs are pulled straight from the ``fastq_ftp`` URLs recorded in the
SRA metadata (md5-verified, resumable). Runs without ENA-hosted FASTQs fall back
to ``prefetch`` + ``fasterq-dump``, which also converts the SRA archive into
FASTQ and needs scratch space for both.
"""

import hashlib
import json
import subprocess
from pathlib import Path


def _md5(path, chunk=1 << 20):
    digest = hashlib.md5()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _download(url, path, expected_md5, curl_bin):
    path = Path(path)
    if path.exists() and expected_md5 and _md5(path) == expected_md5:
        LOGGER.info("%s: cached and md5-verified", path.name)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    target = url if "://" in url else f"https://{url}"
    command = [
        curl_bin,
        "--fail",
        "--location",
        "--silent",
        "--show-error",
        "--retry",
        "3",
        "--continue-at",
        "-",
        "--output",
        str(path),
        target,
    ]
    LOGGER.info("downloading %s", target)
    subprocess.run(command, check=True)
    if expected_md5:
        actual = _md5(path)
        if actual != expected_md5:
            path.unlink(missing_ok=True)
            raise RuntimeError(
                f"md5 mismatch for {path.name}: expected {expected_md5}, got {actual}"
            )


def _ena_fastqs(metadata):
    """Return (urls, md5s) recorded in the SRA metadata, if any."""
    urls = [part for part in (metadata.get("fastq_ftp") or "").split(";") if part]
    md5s = [part for part in (metadata.get("fastq_md5") or "").split(";") if part]
    return urls, md5s


def _from_ena(metadata, outputs, curl_bin):
    urls, md5s = _ena_fastqs(metadata)
    if len(urls) != len(outputs):
        raise RuntimeError(
            f"library has {len(urls)} ENA FASTQ URLs but {len(outputs)} outputs"
        )
    for url, output, expected in zip(urls, outputs, md5s or [""] * len(urls)):
        _download(url, output, expected, curl_bin)


def _from_sra(accession, outputs, prefetch_bin, fasterq_dump_bin, scratch, pigz_bin):
    scratch = Path(scratch)
    scratch.mkdir(parents=True, exist_ok=True)
    LOGGER.info("prefetching %s", accession)
    subprocess.run(
        [
            prefetch_bin,
            "--max-size",
            "100G",
            "--output-directory",
            str(scratch),
            accession,
        ],
        check=True,
    )
    stage = scratch / "fastq"
    stage.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            fasterq_dump_bin,
            "--split-3",
            "--skip-technical",
            "--temp",
            str(scratch / "tmp"),
            "--outdir",
            str(stage),
            str(scratch / accession),
        ],
        check=True,
    )
    produced = sorted(stage.glob(f"{accession}*.fastq"))
    if len(produced) != len(outputs):
        raise RuntimeError(
            f"fasterq-dump produced {len(produced)} files, expected {len(outputs)}"
        )
    for source, output in zip(produced, outputs):
        with open(output, "wb") as out:
            subprocess.run([pigz_bin, "-c", str(source)], stdout=out, check=True)
        source.unlink(missing_ok=True)


def main():
    metadata_path = snakemake.input.metadata
    outputs = list(snakemake.output)
    metadata = json.loads(Path(metadata_path).read_text())
    accession = snakemake.params.run

    urls, _ = _ena_fastqs(metadata)
    if urls:
        if len(urls) != len(outputs):
            raise RuntimeError(
                f"{accession}: layout mismatch, ENA lists {len(urls)} FASTQs "
                f"but the rule expects {len(outputs)}"
            )
        _from_ena(metadata, outputs, snakemake.params.curl)
    else:
        _from_sra(
            accession,
            outputs,
            snakemake.params.prefetch,
            snakemake.params.fasterq_dump,
            snakemake.params.scratch,
            snakemake.params.pigz,
        )

    LOGGER.info("%s: %d FASTQ file(s) ready", accession, len(outputs))


from script_logging import setup as _setup

LOGGER = _setup("fetch_fastq")


if __name__ == "__main__":
    main()
