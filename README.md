# Factory AI Investigator — Nebius × NVIDIA Edition

An evidence-seeking assistant for investigating machine anomaly alerts.

**Demo:** https://factory-investigator-nebius.web.app  
**Track:** Best Apps and Agents  
**Model:** `nvidia/nemotron-3-super-120b-a12b`  
**Inference provider:** Nebius Token Factory

> This prototype uses synthetic factory data and demonstration manuals.
> It does not confirm physical faults or replace approved maintenance procedures.

## What it does

Factory AI Investigator helps users inspect historical anomaly events across
five machines, M-101 through M-105.

Users can:
- Inspect sensor readings and recorded detection events.
- Open saved cloud demonstrations.
- Request a background investigation.
- Inspect tool activity and cited evidence.
- Read observations, unresolved gaps and recommended evidence.
- Save shared review notes.

Google sign-in is required. Saved demonstrations can be viewed without
a new model call.

## What is new in this edition?

This project builds on our earlier Project prototype.

### Reused foundation
- Synthetic factory datasets and machine profiles.
- Frozen XGBoost anomaly classifier and feature engineering.
- Machine-aware manual retrieval using BGE embeddings and Qdrant.
- Dashboard design and cloud deployment experience.

### Added for the Nebius × NVIDIA submission
- NVIDIA Nemotron inference through Nebius Token Factory.
- Model-selected evidence requests and iterative reassessment.
- Generalized evidence tools for all five machines.
- Python-enforced machine scope and evidence cutoff.
- Validated observation IDs and follow-up selections.
- Bounded execution with saved investigation traces.
- Structured reports with clickable evidence sources.
- A separate cloud deployment and dashboard integration.

The earlier edition used Gemini. The investigation workflow submitted
in this edition uses Nemotron.

## How the investigation works

1. Resolve the selected machine and investigation cutoff.
2. Compute a trigger-window versus reference-window comparison in Python.
3. Ask Nemotron to select observations and permitted evidence requests.
4. Execute the selected Python tools.
5. Reassess the accumulated evidence and remaining gaps.
6. Stop within the execution limit and generate a validated report.
7. Save the report and trace for dashboard inspection.

The agent permits up to four additional evidence-tool attempts after the
initial comparison. This is an execution limit, not a dollar-credit limit.

## Evidence tools

| Tool | Purpose |
|---|---|
| `compare_sensor_windows` | Calculate reference and trigger statistics |
| `inspect_trigger_readings` | Inspect individual trigger-window readings |
| `get_prior_calibration_records` | Retrieve earlier calibration records |
| `get_prior_machine_logs` | Search logs within the stated scope |
| `search_machine_manuals` | Retrieve machine-specific and general passages |

Python calculates numerical facts. Nemotron selects permitted IDs and
decides which available evidence to request.

Empty search results are preserved. Missing records do not establish
that nothing happened.

## Architecture

- **Detection:** frozen XGBoost classifier; 30-minute windows; 96 features.
- **Reasoning:** NVIDIA Nemotron through Nebius Token Factory.
- **Retrieval:** BGE embeddings and Qdrant.
- **API:** FastAPI on Google Cloud Run.
- **Background execution:** Cloud Run Jobs.
- **Historical data:** BigQuery.
- **Artifacts, reports and traces:** Cloud Storage.
- **Progress and shared reviews:** Firestore.
- **Frontend and authentication:** Firebase Hosting and Google sign-in.
- **Credentials:** Google Secret Manager for deployed inference access.

Application hosting uses Google Cloud. Runtime model inference uses Nebius.
No Nebius GPU instances or Serverless Jobs are used.

## Repository structure

```text
public-nebius/          Dashboard
src/nebius_*           API and shared validation
src/rag/               Manual loading and retrieval
scripts/               Evidence tools, agent loop and report generation
deploy/                Setup and deployment scripts
data/manuals/          Synthetic reference documents
data/nebius/           Selected demonstration cases
```

Older prototype files remain for provenance. Use the Nebius-specific
configuration files for this edition.

## Local setup

Requirements:
- Python 3.12
- uv
- Nebius Token Factory API access
- Google Cloud and Firebase CLIs for deployment

```powershell
uv sync
```

Create an untracked `.env` file:

```dotenv
NEBIUS_API_KEY=your_key_here
NEBIUS_BASE_URL=https://api.tokenfactory.us-central1.nebius.com/v1/
NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b
```

Never commit API keys, service-account credentials or `.env`.

### Offline tool checks

```powershell
uv run python scripts/check_multimachine_tools.py
```

These checks use synthetic fixtures. They do not establish live inference,
retrieval quality or cloud deployment correctness.

### Local investigation

After provisioning the required datasets and retrieval artifacts:

```powershell
uv run python scripts/test_sensor_tool.py
```

Inspect the script's CLI options before selecting a different machine or cutoff:

```powershell
uv run python scripts/test_sensor_tool.py --help
```

## Data and retrieval artifacts

Large datasets and embedding-model archives are excluded from Git.

The current workflow requires:
- `data/yearly_experiment_v3/raw/sensors.csv`
- `data/yearly_experiment_v3/raw/maintenance_history.csv`
- `data/yearly_experiment_v3/raw/machine_logs.csv`
- `artifacts/rag/v1/manifest.json`
- `artifacts/rag/v1/manual_points.jsonl.gz`
- `artifacts/rag/v1/embedding_model.tar.gz`

Cloud deployment also uses historical BigQuery tables and selected cases.

The supplied deployment scripts reference the project's provisioned resources.
They are not a one-command installation into an arbitrary new project.
An independent public data/artifact provisioning route is not yet packaged.
The hosted demonstrations provide access to existing results.

## Deployment

Review project IDs, service accounts, bucket names and configuration before
running deployment scripts.

The Nebius edition uses the separate project `factory-investigator-nebius`.

```powershell
.\deploy\setup_nebius.ps1
.\deploy\set_nebius_secret.ps1
.\deploy\setup_nebius_dashboard.ps1
uv run python deploy/copy_history_nebius.py
.\deploy\deploy_nebius_dashboard.ps1
firebase deploy --only "hosting,firestore:rules" --config firebase.nebius.json --project factory-investigator-nebius
```

These commands create or modify cloud resources and may incur charges.
Google sign-in must be enabled in Firebase Authentication.

## Verification completed

- Offline multi-machine tool checks passed.
- Cloud batch execution produced reports and traces for all five machines.
- The saved M-101 dashboard report was inspected.
- Independent CSV checks reproduced its reported sensor differences.
- Calibration filtering, log scope and manual passages were checked for M-101.

These checks are not a broad report-quality benchmark.

## Limitations

- Operational data is synthetic.
- Manuals are not verified OEM instructions.
- Sensor units, locations and operating limits are unverified.
- A reference window is not a verified healthy baseline.
- Citation-ID validation does not establish claim support.
- No controlled model comparison or measured maintenance savings is claimed.
- Historical incidents are not currently retrieved by an agent tool.
- Live sensor replay from the earlier edition is not connected here.
- Shared reviews do not establish professional qualifications or confirm faults.

## Next steps

- Complete and document fresh dashboard-triggered investigation testing.
- Evaluate the agent against a fixed retrieval baseline.
- Measure latency, token usage and evidence coverage.
- Add operating-state and historical-incident tools.
- Improve claim-level evidence validation.
- Test with verified documentation and maintenance-engineer feedback.

## AI assistance

Runtime investigation decisions
use NVIDIA Nemotron through Nebius Token Factory.

## License

See `LICENSE`. Third-party models, libraries and services retain their
respective licenses and terms.
