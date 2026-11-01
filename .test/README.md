# Catalog test case

This directory lets the Snakemake workflow catalog generate a rulegraph without
network access or model calls:

```bash
snakemake -s workflow/Snakefile -d .test -c 1 --forceall --rulegraph
```

The configuration is deliberately minimal. It is not a data test case.
