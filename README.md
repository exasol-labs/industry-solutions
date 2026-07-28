# Exasol Industry Solutions

Reference solutions, deployment patterns, and end-to-end demos that show how to
build real workloads on [Exasol](https://www.exasol.com). Each solution is a
self-contained folder with everything needed to understand, deploy, and adapt it:
SQL, scripts, container definitions, architecture notes, and a walkthrough.

These are practical, runnable starting points for common industry problems, from
real-time fraud detection to analytical pipelines and in-database machine learning.

## Solutions

<!-- SOLUTIONS:START -->

| Solution | Industry | Description |
| --- | --- | --- |
| [Process Mining Demonstrator](process-mining-demonstrator/) | Cross-Industry | A native **macOS** process-mining application for **Apple Silicon** Macs. Process Mining Demonstrator connects to an Exasol database, reads a journey/event log, and renders how real cases flow through your business processes as an interactive map — with rich filtering, A/B comparison, Monte Carlo simulation, conformance checking, and optional AI-assisted documentation. |
| [Real-Time Banking Fraud Detection](realtime-banking-fraud-detection/) | Banking & Financial Services | End-to-end banking fraud pipeline: PostgreSQL OLTP -> Kafka CDC with Debezium -> Exasol analytics -> in-database ML scoring. |

<!-- SOLUTIONS:END -->

> The table above is generated automatically from each solution folder by
> [`scripts/generate_solutions_index.py`](scripts/generate_solutions_index.py).
> Do not edit it by hand.

## How a Solution Is Organized

Every solution lives in its own top-level folder and is fully self-contained, so
you can copy a single folder and have everything you need:

```text
<solution-name>/
├── README.md            # What it does, architecture, quick start
├── docs/                # Deeper architecture, guides, customer brief, assets
├── *.sql                # Schema, UDFs, and analytics scripts
├── docker-compose.yml   # Local stack, where applicable
├── deploy.sh / .ps1     # Deployment scripts
└── requirements.txt     # Dependencies, where applicable
```

Each solution README leads with the business problem it solves, the architecture,
and a quick start, so you can evaluate fit before deploying anything.

## Getting Started

1. Browse the [solutions table](#solutions) and open the folder that matches your
   use case.
2. Follow that solution's `README.md`. Quick starts assume you run commands from
   inside the solution folder.
3. Most solutions expect access to an Exasol database. If you do not have one,
   see the [Exasol Docker / Community Edition](https://github.com/exasol/docker-db)
   and [Exasol documentation](https://docs.exasol.com).

## Contributing a Solution

We welcome new industry solutions. To add one:

1. Create a top-level folder in kebab-case (for example `retail-demand-forecasting/`).
2. Add a `README.md` whose first `# H1` is the solution title, followed by a one or
   two sentence lead paragraph describing the business outcome. That title and
   paragraph populate the solutions table automatically.
3. (Optional) Add metadata for the table by placing a leading HTML comment at the
   very top of the solution README:

   ```markdown
   <!--
   industry: Banking & Financial Services
   status: stable
   -->

   # Real-Time Banking Fraud Detection
   ```

4. Keep the solution self-contained: do not rely on repo-root files at runtime.
5. Run `python scripts/generate_solutions_index.py` to refresh the table locally,
   or let the GitHub Action update it on merge.

## Support and Disclaimer

These solutions are reference implementations maintained by Exasol Labs to
demonstrate patterns and accelerate evaluation. They are provided as-is and are
not part of the supported Exasol product. For production deployments, review and
adapt each solution to your own security, compliance, and operational requirements.

For questions about Exasol itself, see the [official documentation](https://docs.exasol.com)
or [contact Exasol](https://www.exasol.com/contact/).

## License

See [LICENSE](LICENSE). Unless stated otherwise within a solution folder, the
contents of this repository are released under the terms in that file.
