# Methods

## Overview of the classification workflow

We developed a Snakemake (9.27.1; Python 3.12) workflow that annotates Arabidopsis
thaliana RNA-seq libraries submitted to the sequence read archive (SRA). We
defined the input as a tabular sample sheet (one row per run) containing the run
accession, BioSample accession, BioProject accession, and species. The workflow
fetches structured metadata from NCBI, retrieves the publication associated with
each BioProject from Europe PMC, summarizes the experimental conditions
described in each paper, classifies the RNA type of every run, retains only
mRNA-sequencing libraries, and assigns four annotations per retained run: a
tissue category, a germplasm class, a PECO plant-exposure term set, and a PECO
study-condition term. We structured every step as a Snakemake rule with a
dedicated conda environment (`--software-deployment-method conda`), grouped the
rules under a shared `workflow/` tree at the repository root, and validated the
configuration and sample sheet against JSON Schema specs (jsonschema 4.26.0) at
graph build time. To process the full archive in manageable units, we
implemented optional window batching: when the user supplies `batch_size` and
`batch_index` (both unset by default), the Snakefile slices the sample sheet
into non-overlapping, ordered windows, and the aggregation rule rescans the
full sheet at every invocation so that output labels accumulate across
invocations. We ran all commands from the repository root and cached every
fetched record as one JSON file per accession under `results/metadata/`; the
manual-curation zone `resources/` remains empty.

## SRA and BioSample metadata retrieval

We retrieved run-level metadata with NCBI E-utilities `efetch` against `db=sra`
(50 accessions per request) and sample-level metadata against `db=biosample`
(200 accessions per request), throttling consecutive requests by 0.35 s and
retrying transient failures up to five times (backoff for HTTP 429; NCBI
api_key optional via the `NCBI_API_KEY` environment variable). We parsed each
record into a normalized JSON object retaining the experiment accession, model
and instrument identifiers, library strategy/selection/source, library
construction protocol, experiment attributes, and all BioSample attributes
(preferring the `harmonized_name` when present). Because ENA-submitted
libraries (SAMEA accessions) are frequently absent from the NCBI BioSample
mirror, we added a fallback: for any accession absent at NCBI, we requested the
INSDC BioSample XML from the ENA API (three attempts, 0.3 s pacing) and parsed
it into the same normalized shape, recording `fetch_source: "ena"` versus
`"ncbi"`; accessions missing from both sources abort the window with an
explicit error. In a dry-run validation the workflow resolved both NCBI
(SAMN/SRX) and ENA (SAMEA/ERX) records for test windows.

## BioProject, publication, and paper-text retrieval

We resolved each BioProject accession to its NCBI UID with `esearch`
(`db=bioproject`), linked it to PubMed records with `elink`
(`dbfrom=bioproject, db=pubmed`), and discarded projects without at least one
linked publication. For each linked project we queried the Europe PMC REST
service (`/search`, `resultType=core`) for the first matching PMID; we stored
the full article metadata when an open-access PMCID existed and requested the
full-text XML (`/rest/{pmcid}/fullTextXML`), otherwise we stored the abstract
and flagged the record `status: "abstract"`. We paced Europe PMC requests by
the same 0.35 s interval and cached one JSON record per BioProject.

## Per-project condition summarization

For every paper-bearing BioProject, we built a compact excerpt (maximum 12,000
characters) from the full-text XML by selecting the title, abstract,
methods-related sections (matched by section title), and figure/table
captions. We submitted this excerpt to the qwen3.8 model (temperature 0,
served through Ollama's OpenAI-compatible API) with a prompt instructing
extraction of the conditions that apply to the RNA-seq samples as a fixed JSON
schema: `genotype`, `treatment`, `growth_conditions`, `tissue_sampled`,
`stress`, `evidence` (short supporting quotes), and additionally
`day_length_hours` (hours of light per day, or null) and
`growth_temperature_c` (midpoint of any stated range, or null). We coerced
non-numeric values to null, required null rather than invented values when the
paper does not report a field, and executed this step once per project with
results reused by every run in the project.

## PECO ontology index

We downloaded the Plant Experimental Conditions Ontology (PECO) in OWL format
from the OBO Foundry persistent URL (`purl.obolibrary.org/obo/peco.owl`,
`curl`, three retries) and parsed it with pronto (2.7.4). We assembled one
record per non-obsolete PECO term containing the term identifier, label,
definition (source citation stripped), curated synonym list (scope suffixes
removed), and parent identifiers, and classified each term by ancestry:
`study_condition` for descendants of PECO:0007231, otherwise `exposure` for
descendants of PECO:0001001, otherwise `other`; terms additionally flagged
with the descendant set of PECO:0007147 were marked `growth_system`. At the
time of the index build the exposure branch contained 511 descendant terms and
the study-condition branch contained 4. We indexed synonyms in a lowercase
lookup table and embedded every term as `"<label>. <definition>;<synonyms>"`
using the BAAI/bge-base-en-v1.5 sentence transformer (sentence-transformers
6.2.0, torch 2.15.0+cpu, normalized embeddings, batch size 64) stored as a
float32 matrix aligned with the term list.

## RNA-type classification and inclusion filter

We classified the RNA type of every run with a rules-first hybrid. Deterministic
rules read discrete structured fields and applied boundary-anchored regular
expressions to free text: exact matches of `library_strategy` against curated
lowercase sets (e.g. `miRNA-Seq` to small RNA) and `library_selection` against
poly(A)/oligo(dT) (mRNA), RiboZero/rRNA-depletion (ribo-depleted total RNA), and
size-fractionation (small RNA) pattern classes; additional expression patterns
over BioSample and SRA text resolved total RNA, miRNA/piRNA/siRNA/snoRNA/snRNA/
tRNA-specific annotations, long non-coding RNA, circular RNA, and non-RNA
assays (e.g. WGS, ChIP-Seq). Conflicting rule candidates produced `unknown`
rather than a guess, and absence of rule candidates deferred to the
decision model. In the model step we submitted all evidence lines to the Tev1
4B decision model (temperature 0, via Ollama's `/v1/systemone` endpoint) with
one structured question per RNA type; on failure we fell back to a
constrained-JSON chat completion by qwen3.8 (temperature 0). We accepted
`mrna` and `ribo_depleted_total_rna` as eligible (configurable in
`rna_type.accepted_rna_types`), flagged classifications below a 0.6 confidence
threshold for review, and recorded the source (`rules`, `decision`,
`chat_fallback`), confidence, and evidence string per run. Non-eligible runs
wrote a minimal stub and skipped all downstream labeling; the aggregation rule
wrote them to a separate exclusions table.

## Tissue classification

We assigned one of seven tissue categories (`whole_plant`, `shoot`, `root`,
`leaf`, `seed`, `flower`, `fruit`) per run. We first applied curated
boundary-anchored keyword lists over the BioSample, SRA, paper-summary, and
ATHRDB evidence, and abstained whenever the keywords matched more than one
category; the deterministic layer otherwise assigned the category with no
model call. For runs the rules could not decide, we used the Tev1 4B decision
model (temperature 0) with one question per candidate category over a short
state comprising the evidence lines and paper conditions, selecting the
highest-probability choice among the seven categories plus an `OTHER` sentinel
(described to the model as "tissue not in the list or ambiguous"; the paper's
conventions with flower and fruit separated from shoot informed this choice).
When the decision call failed we fell back to a constrained-JSON chat
completion by qwen3.8 (temperature 0). We recorded the chosen category,
source, confidence, and evidence, and flagged decisions below 0.6 confidence
or equal to `OTHER` for human review.

## Germplasm classification

We classified each run as `natural_accession`, `mutant`, `transgenic`,
`hybrid`, `grafted`, `cell_culture`, `polyploid`, `aneuploid`, or `unknown`. A
deterministic layer applied curated regular expressions over the evidence
lines (mutagenesis and transformation vocabulary including CRISPR, and
genotype tokens such as `ros1 dml2 dml3` resolved as mutant), ranked by a
fixed priority order, and identified natural accessions either by the curated
accession list (including `Col-0`, `Columbia`, `Landsberg erecta`; case
insensitive) or by an accession-shaped token pattern; because ENA records
spell accessions differently from GEO records, the list was assembled from
both vocabularies. We guarded the natural-accession call against compound
genotypes: the call required every token of every genotype field to be either
a listed accession, an accession-shaped token, or a neutral token (e.g.
`wild type`, `wt`). Undecided runs were labeled by the Tev1 4B decision model
(temperature 0) with one question per category over the evidence and paper
state, with qwen3.8 (temperature 0) as the constrained-JSON fallback. We
recorded the class, the natural-accession flag, source, confidence, and
evidence, and flagged `unknown` and sub-0.6-confidence calls for review.

## PECO exposure labeling

We assigned zero or more PECO exposure terms (branch PECO:0001001, 511 terms)
per run. We first composed a query from the evidence lines (BioSample and SRA
attributes, ATHRDB curation, the paper condition summary including
day length and temperature) and retrieved candidates in two stages: exact and
boundary-anchored lexical matches over labels and synonyms, followed by
cosine-similarity ranking against the bge-base embeddings up to a configurable
budget (top-30 candidates). We submitted the sample evidence and the candidate
terms (identifier, label, trimmed definition) to qwen3.8 (temperature 0) and
required a JSON response selecting any subset of the candidate terms as
`terms`, each with a one-line evidence quote, or reporting `no_condition`
(nothing experimental to annotate) or `other` (a condition exists but no
candidate fits) with a free-text `suggested_label`. We validated every
returned identifier against the exposure branch, dropped invalid choices
before recording, computed the maximum candidate retrieval score, and flagged
runs for review when no valid terms were accepted with `other` set, when the
top retrieval score fell below 0.55, or when the underlying model call was
low-confidence. Terms additionally flagged `growth_system` (branch
PECO:0007147) populated derived growth-system identifier and label columns.

## PECO study-condition labeling

We assigned one PECO study condition term per run by submitting the full
study-condition branch (all 4 descendant terms of PECO:0007231) to the Tev1
4B decision model (temperature 0) as one question per term over the evidence
state, with an `OTHER` sentinel for none of the listed terms and a
constrained-JSON qwen3.8 (temperature 0) fallback; we flagged sub-0.6
confidence or sentinel selections for review. Because the branch is small, we
passed every term and definition directly and did not perform retrieval.

## Aggregation and quality-control flags

We combined all per-run outputs into one table with a single aggregation rule.
The rule reread the full sample sheet every invocation, imported the RNA-type
classification for every run, and wrote eligible, fully labeled runs to
`results/labels.tsv` and ineligible runs to `results/labels.excluded.tsv`
(run, BioSample, BioProject, species, RNA type and subtype, ribo-depletion
flag, classification source, confidence, evidence, and exclusion reason). For
included runs the table carries the four annotations with per-step source,
confidence, and evidence fields, the derived `is_natural_accession` flag, the
growth-system columns, paper-reported day length and temperature, ATHRDB
curation columns, and review flags. We composed review flags from the
per-step thresholds (0.6 for tissue, germplasm, study condition, and RNA
type; 0.55 for the exposure retrieval score) and paper-evidence flags
(missing paper or abstract-only summary), joined them as semicolon-separated
short codes (`tissue_other`, `tissue_low_confidence`, `germplasm_unknown`,
`peco_other`, `peco_weak_retrieval`, `no_condition`, `no_paper`,
`paper_low_confidence`, `rna_type_low_confidence`), and marked affected rows
`review_required`. Runs whose classification chain had not completed were
counted and reported rather than silently dropped.

## PlantRNADB curation lookup

For every Arabidopsis run we additionally recorded the community-curated
annotations published by the PlantRNADB Arabidopsis database. We resolved the
run's experiment accession (SRX/ERX) to a GEO sample accession (GSM) with
NCBI `esearch`/`esummary` against `db=gds`, then requested the PlantRNADB
per-library page (`Search.php?query=<GSM>/0/max/NAN/NAN/NAN/`) and parsed both
HTML tables into a structured record (curated tissue, genotype, ecotype,
project, release date, total reads, and mapped rate). We executed all lookups
in one serial workflow job to bound the request rate: a minimum gap of 2.0 s
between requests augmented by one-sided random jitter of up to 25% of the gap
(never below the configured floor), a hard limit of 5000 requests per job with
remaining runs stubbed for retrieval in a later invocation, a 60 s per-request
timeout, and caching that skips runs already fetched. Failures were recorded
as stubs with an explanatory note and never aborted the workflow. Runs
without a GEO record were stubbed (`no_geo_record`), because the database is
GEO-keyed and ENA-only libraries fall outside its coverage. Curated tissue,
genotype, and ecotype lines were appended to the tissue and germplasm evidence
streams as independent observations, and the curation columns were carried
into the aggregate table for cross-checking during review rather than treated
as authoritative labels.

## Human review application

We built a Streamlit (1.66.1) browser application backed by SQLite (write-ahead
logging) that imports `results/labels.tsv` and every per-run artifact, groups
runs by BioProject, and presents, per run, the linked paper with reported day
length and temperature, BioProject/BioSample/SRA metadata, ATHRDB curation,
model evidence, and editable tissue, germplasm, exposure (searchable
multi-select over label, identifier, synonym, and definition), and
study-condition fields. We recorded every edit and review action in an
append-only event log with reviewer name (self-declared) and UTC timestamp,
counted a run as reviewed only after an explicit confirmation, recomputed the
derived fields on save, and exported the human-reviewed table
(`labels.reviewed.csv`/`.tsv`) by replaying latest-edit events over the
imported base; the original workflow outputs remained unmodified.

## Compute environment

We executed the workflow on the Savio BRC cluster (UC Berkeley). One
high-memory H200 GPU job served qwen3.8 and Tev1 via Ollama (0.40.11,
Vulkan backend, models on scratch, keep-alive 2 h) bound to all interfaces,
and the CPU rules ran as Slurm jobs (Snakemake Slurm executor plugin 2.8.0,
partition `savio4_htc`, QoS `moilab_htc4_normal`, account `co_moilab`, 1 CPU
and 4 GB memory per job, 12 h limit, up to 16 concurrent jobs) connected to
the shared model server by URL. A launcher script submitted the server job,
waited for readiness (up to 1 h), verified login-node connectivity,
propagated the server URL to the workflow rules, and canceled the server on
exit. We deployed conda environments automatically per rule (`--sdm conda`),
pinned Python 3.12 in every rule environment, and placed the Hugging Face
model cache on scratch storage.