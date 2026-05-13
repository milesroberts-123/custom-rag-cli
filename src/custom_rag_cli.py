#!/global/scratch/users/milesroberts/envs/ollama/bin/python
"""
CLI tool for annotating biosamples from RNA-seq experiments with tissue type,
PECO treatment conditions, and study type using scientific paper PDFs and a
local LLM via Ollama + LlamaIndex.

For every biosample in the metadata file, the script:
  1. Retrieves relevant context from PDFs via RAG,
  2. Presents the metadata, context, and available PECO terms to the LLM,
  3. Parses the LLM's classification response,
  4. Writes a tab-separated output file.
"""
import csv
import os
import re
import sys
import click
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.llms.ollama import Ollama
from llama_index.embeddings.ollama import OllamaEmbedding


# ═══════════════════════════════════════════════════════════════════════════════
#  Parsers
# ═══════════════════════════════════════════════════════════════════════════════

def parse_biosample_metadata(filepath):
    """
    Parse a biosample metadata file into a list of records.

    Expected format (from biosample_result.txt)::

        1: Cat-0 (9832)
        Identifiers: BioSample: SAMN04910990; SRA: SRS1416138; GEO: GSM2136304
        Organism: Arabidopsis thaliana
        Attributes:
            /source name="rosette leaves"
            /cultivar="Cat-0"
            /ecotype id="9832"
            /development stage="before bolting"
            /light condition="long day"
            /tissue="leaf"
        Accession: SAMN04910990    ID: 4910990

    Returns a list of dicts with keys:
        biosample_id, organism, cultivar, attributes (dict), raw_text
    """
    records = []
    with open(filepath, 'r') as fh:
        content = fh.read()

    # Entries are separated by a blank line followed by a numbered header
    blocks = re.split(r'\n(?=\d+: )', content.strip())

    for block in blocks:
        if not block.strip():
            continue

        rec = {'attributes': {}, 'raw_text': block.strip()}

        for line in block.split('\n'):
            line = line.strip()

            m = re.search(r'BioSample:\s*(\S+)', line)
            if m:
                rec['biosample_id'] = m.group(1).rstrip(';')

            m = re.search(r'Organism:\s*(.+)', line)
            if m:
                rec['organism'] = m.group(1).strip()

            m = re.match(r'/([\w\s]+)="([^"]*)"', line)
            if m:
                key = m.group(1).strip()
                val = m.group(2).strip()
                rec['attributes'][key] = val
                if key in ('cultivar', 'ecotype'):
                    rec['cultivar'] = val

        if 'biosample_id' in rec:
            records.append(rec)

    return records


def parse_peco_csv(filepath):
    """
    Parse PECO.csv into a list of {id, label, definition} dicts.

    The CSV uses commas as delimiters but the *Definitions* column may contain
    internal commas.  We locate the ``Obsolete`` column (always ``TRUE`` or
    ``FALSE`` preceded by a comma) and use it to anchor the definition field.
    """
    terms = []
    with open(filepath, 'r') as fh:
        lines = fh.readlines()

    for lineno, line in enumerate(lines):
        line = line.rstrip('\n\r')
        if lineno == 0 or not line:          # skip header & blank lines
            continue

        m = re.search(r'PECO_(\d+)', line)
        if not m:
            continue

        peco_num = m.group(1)
        peco_id = f'PECO:{peco_num}'
        url_end = line.find(f'PECO_{peco_num}') + len(f'PECO_{peco_num}')

        # The Obsolete column (5th) is always ",TRUE," or ",FALSE,"
        obs = re.search(r',(?:TRUE|FALSE),', line)
        if not obs:
            continue

        # Everything between the URL and the Obsolete marker is cols 2-4
        middle = line[url_end + 1:obs.start()]

        # Column 2 = Preferred Label  (no internal commas in PECO)
        # Column 3 = Synonyms        (no internal commas)
        # Column 4 = Definitions     (may contain commas)
        comma_positions = [p for p, ch in enumerate(middle) if ch == ',']

        if len(comma_positions) < 2:
            continue

        label = middle[:comma_positions[0]]
        definition = middle[comma_positions[1] + 1:]

        terms.append({
            'id': peco_id,
            'label': label.strip(),
            'definition': definition.strip(),
        })

    return terms


# ═══════════════════════════════════════════════════════════════════════════════
#  Formatters
# ═══════════════════════════════════════════════════════════════════════════════

def format_peco_for_prompt(terms, max_def_len=120):
    """Render PECO terms as a compact, human-readable list for the prompt."""
    out = []
    for t in terms:
        d = t['definition']
        if len(d) > max_def_len:
            d = d[:max_def_len].rsplit(' ', 1)[0] + '...'
        out.append(f"  {t['id']}  {t['label']}  —  {d}")
    return '\n'.join(out)


def format_biosample_for_prompt(rec):
    """Render a single biosample record as human-readable text."""
    parts = [f"BioSample: {rec['biosample_id']}"]
    if rec.get('organism'):
        parts.append(f"Organism: {rec['organism']}")
    if rec.get('cultivar'):
        parts.append(f"Cultivar: {rec['cultivar']}")
    parts.append('Attributes:')
    for k, v in rec['attributes'].items():
        parts.append(f'  {k}: {v}')
    return '\n'.join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
#  LLM response parser
# ═══════════════════════════════════════════════════════════════════════════════

VALID_TISSUES = {'leaf', 'root', 'shoot', 'fruit', 'flower', 'seed',
                 'whole plant'}

TISSUE_ALIASES = {
    'leaves': 'leaf',
    'leaf tissue': 'leaf',
    'roots': 'root',
    'root tissue': 'root',
    'shoots': 'shoot',
    'shoot tissue': 'shoot',
    'fruits': 'fruit',
    'flowers': 'flower',
    'seeds': 'seed',
    'whole_plant': 'whole plant',
    'entire plant': 'whole plant',
    'rosette': 'leaf',
    'rosette leaf': 'leaf',
    'rosette leaves': 'leaf',
}

VALID_STUDIES = {'laboratory', 'growth chamber', 'greenhouse',
                 'outdoor/field'}

STUDY_ALIASES = {
    'lab': 'laboratory',
    'lab study': 'laboratory',
    'growth_chamber': 'growth chamber',
    'controlled environment': 'growth chamber',
    'controlled environment chamber': 'growth chamber',
    'field': 'outdoor/field',
    'outdoor': 'outdoor/field',
    'field study': 'outdoor/field',
    'field experiment': 'outdoor/field',
    'open field': 'outdoor/field',
}


def _normalize_choice(raw, valid_set, aliases):
    """Normalize a raw LLM output token to a canonical value from valid_set."""
    clean = raw.strip().lower().replace('_', ' ')
    if clean in valid_set:
        return clean
    if clean in aliases:
        return aliases[clean]
    for alias, canon in aliases.items():
        if alias in clean and len(alias) > 3:
            return canon
    for t in sorted(valid_set, key=len, reverse=True):
        if t in clean:
            return t
    return raw.strip()


def parse_llm_response(text):
    """
    Extract tissue type, PECO terms, and study type from LLM output.

    Lines should follow::

        TISSUE: <value>
        PECO: <value>
        STUDY: <value>

    Fuzzy-matches against VALID_TISSUES / VALID_STUDIES when possible.
    """
    result = {'tissue_type': '', 'treatment_conditions': '', 'study_type': ''}

    for raw_line in text.split('\n'):
        line = raw_line.strip()
        upper = line.upper()

        if upper.startswith('TISSUE:'):
            val = line.split(':', 1)[1].strip()
            result['tissue_type'] = _normalize_choice(
                val, VALID_TISSUES, TISSUE_ALIASES)

        elif upper.startswith('PECO:'):
            result['treatment_conditions'] = line.split(':', 1)[1].strip()

        elif upper.startswith('STUDY:'):
            val = line.split(':', 1)[1].strip()
            result['study_type'] = _normalize_choice(
                val, VALID_STUDIES, STUDY_ALIASES)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Prompt template
# ═══════════════════════════════════════════════════════════════════════════════

PROMPT_TEMPLATE = """\
You are a plant biology researcher annotating biosamples with metadata.

For the biosample described below, use the provided context from scientific
papers and the provided list of PECO (Plant Experimental Conditions Ontology)
terms to determine:

1. TISSUE TYPE — Choose ONE from: leaf, root, shoot, fruit, flower, seed, whole plant
2. TREATMENT CONDITIONS — Choose the most appropriate PECO term(s) from the
   provided list that describe the environmental, growth, or treatment
   conditions.  Return PECO ID and preferred label.  Separate multiple terms
   with semicolons if applicable.
3. STUDY TYPE — Choose ONE from: laboratory, growth chamber, greenhouse, outdoor/field

If exact conditions are unclear from the metadata or context, make your best
inference based on the available information.

{instructions}

BIOSAMPLE METADATA:
{biosample_metadata}

RELEVANT CONTEXT FROM SCIENTIFIC PAPERS:
{context}

AVAILABLE PECO ONTOLOGY TERMS (ID label — definition):
{peco_terms}

Respond in this EXACT format with NO additional commentary:
TISSUE: <tissue_type>
PECO: <peco_id_1: label_1; peco_id_2: label_2>
STUDY: <study_type>\
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════════════════════

@click.command()
@click.option(
    '--instructions', default='',
    help='Custom natural-language instructions for mapping labels onto '
         'biosamples (any text).')
@click.option(
    '--pdfs', required=True,
    help='Path to folder containing PDF scientific papers.')
@click.option(
    '--metadata', required=True,
    help='Path to biosample metadata file '
         '(format like test/biosample_result.txt).')
@click.option(
    '--peco', required=True,
    help='Path to PECO ontology terms CSV (format like test/PECO.csv).')
@click.option(
    '--model', default='gemma3:1b', show_default=True,
    help='Ollama model name.')
@click.option(
    '--temperature', default=0.0, show_default=True,
    help='LLM temperature (0 = deterministic).')
@click.option(
    '--context-window', default=4096, show_default=True,
    help='Context window size in tokens.')
@click.option(
    '--topk', default=5, show_default=True,
    help='Number of similar document chunks to retrieve per query.')
@click.option(
    '--output', default='biosample_annotations.tsv', show_default=True,
    help='Output TSV file path.')
@click.option(
    '--start', default=0, show_default=True,
    help='0-based start index in biosample list '
         '(for resuming interrupted runs).')
@click.option(
    '--limit', default=0, show_default=True,
    help='Maximum number of biosamples to process (0 = all).')
def main(instructions, pdfs, metadata, peco, model, temperature,
         context_window, topk, output, start, limit):
    # ── Validate inputs ──────────────────────────────────────────────────
    if not os.path.isdir(pdfs) and not os.path.isfile(pdfs):
        click.echo(f"ERROR: --pdfs path does not exist: {pdfs}", err=True)
        sys.exit(1)
    for flag, path in [('--metadata', metadata), ('--peco', peco)]:
        if not os.path.isfile(path):
            click.echo(f"ERROR: {flag} file not found: {path}", err=True)
            sys.exit(1)

    # ── Header ───────────────────────────────────────────────────────────
    click.echo('=' * 60)
    click.echo('  Biosample Metadata Annotator')
    click.echo('=' * 60)

    # ── Load data ────────────────────────────────────────────────────────
    click.echo('\n[1/4] Loading PECO ontology terms ... ', nl=False)
    peco_terms = parse_peco_csv(peco)
    click.echo(f'{len(peco_terms)} terms loaded')

    click.echo('[2/4] Loading biosample metadata ... ', nl=False)
    biosamples = parse_biosample_metadata(metadata)
    click.echo(f'{len(biosamples)} biosamples loaded')

    click.echo('[3/4] Loading PDF documents ... ', nl=False)
    if os.path.isdir(pdfs):
        reader = SimpleDirectoryReader(pdfs, recursive=True,
                                       required_exts=['.pdf'])
    else:
        reader = SimpleDirectoryReader(input_files=[pdfs])
    docs = reader.load_data()
    click.echo(f'{len(docs)} document(s) loaded')

    # ── Configure LLM ────────────────────────────────────────────────────
    click.echo('[4/4] Configuring LLM & embeddings ... ', nl=False)
    Settings.embed_model = OllamaEmbedding(model_name='nomic-embed-text:v1.5')
    Settings.llm = Ollama(
        model=model,
        request_timeout=600.0,
        temperature=temperature,
        context_window=context_window,
    )
    click.echo('done')

    # ── Build index ──────────────────────────────────────────────────────
    click.echo('\nBuilding vector index from PDFs ... ', nl=False)
    index = VectorStoreIndex.from_documents(docs)
    retriever = index.as_retriever(similarity_top_k=topk)
    click.echo('done')

    # ── Pre-format static prompt pieces ──────────────────────────────────
    peco_text = format_peco_for_prompt(peco_terms)
    instructions_block = (
        f'ADDITIONAL INSTRUCTIONS:\n{instructions.strip()}'
        if instructions.strip() else ''
    )

    # ── Slice biosample list ─────────────────────────────────────────────
    s = int(start)
    e = s + int(limit) if int(limit) > 0 else len(biosamples)
    batch = biosamples[s:e]

    if not batch:
        click.echo('No biosamples to process (check --start / --limit).',
                   err=True)
        sys.exit(0)

    click.echo(f'\nProcessing {len(batch)} biosample(s) '
               f'(indices {s}–{e - 1} of {len(biosamples)})\n')

    # ── Process each biosample ───────────────────────────────────────────
    results = []
    n = len(batch)
    ok = 0

    for i, rec in enumerate(batch):
        bid = rec['biosample_id']
        click.echo(f'[{i + 1}/{n}] {bid}  ', nl=False)

        try:
            meta_text = format_biosample_for_prompt(rec)

            # Query the vector index for relevant paper snippets
            attr_vals = ' '.join(rec['attributes'].values())
            query = f'experimental conditions methods: {attr_vals}'
            nodes = retriever.retrieve(query)
            context = '\n\n'.join(n.text for n in nodes) if nodes else \
                'No specific context found in the provided papers.'

            prompt = PROMPT_TEMPLATE.format(
                instructions=instructions_block,
                biosample_metadata=meta_text,
                context=context,
                peco_terms=peco_text,
            )

            response = Settings.llm.complete(prompt)
            parsed = parse_llm_response(response.text)

            results.append({
                'BioSample': bid,
                'tissue type': parsed['tissue_type'],
                'treatment conditions': parsed['treatment_conditions'],
                'study type': parsed['study_type'],
            })
            ok += 1
            click.echo(f'OK  —  tissue={parsed["tissue_type"]}, '
                       f'study={parsed["study_type"]}')

        except Exception as exc:
            click.echo(f'FAIL  —  {exc}')
            results.append({
                'BioSample': bid,
                'tissue type': 'ERROR',
                'treatment conditions': str(exc)[:200],
                'study type': 'ERROR',
            })

    # ── Write output ─────────────────────────────────────────────────────
    click.echo(f'\n{"=" * 60}')
    click.echo(f'Writing {len(results)} rows to {output} ...')
    with open(output, 'w', newline='') as fh:
        writer = csv.writer(fh, delimiter='\t', lineterminator='\n')
        writer.writerow(['BioSample', 'tissue type',
                         'treatment conditions', 'study type'])
        for r in results:
            writer.writerow([r['BioSample'], r['tissue type'],
                            r['treatment conditions'], r['study type']])

    click.echo(f'Done — {ok}/{n} biosamples annotated successfully.')
    if ok < n:
        click.echo(f'       {n - ok} had errors (see output file for details).')
    click.echo(f'Output: {output}')


if __name__ == '__main__':
    main()
