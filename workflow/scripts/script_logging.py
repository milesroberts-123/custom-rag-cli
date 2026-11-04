"""Per-script logging helper for Slurm job logs.

Every rule script configures one logger with this helper at import time; the
messages stream to stdout, which the Snakemake Slurm executor captures in its
default job log under .snakemake/slurm_logs/. Records are flushed individually
so progress lines appear while the job is still running.
"""

import logging
import sys

FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def setup(name):
    """Return a logger writing formatted, line-flushed records to stdout."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(fmt=FORMAT, datefmt=DATE_FORMAT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
