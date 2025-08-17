# CANON_RAG

Streamlit RAG ultrasound manual

Small Python project; prepared for publishing to GitHub.

What I added for GitHub packaging:
- .gitignore to keep large data out of the repository
- MIT LICENSE
- pyproject.toml to allow building/installing with pip
- .gitattributes
- a basic GitHub Actions workflow (.github/workflows/ci.yml)
- CONTRIBUTING.md

Badges

- CI: ![CI](https://github.com/<your-username>/<repo>/actions/workflows/ci.yml/badge.svg)
- PyPI: ![PyPI](https://img.shields.io/pypi/v/canon_deployment.svg)

Quick start

1. Create a virtualenv and install requirements:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1; python -m pip install --upgrade pip; pip install -r requirements.txt

2. Run the app:

    .\.venv\Scripts\Activate.ps1; python app.py

Notes
- The `processed_data/` folder contains processed images and is included in this repository so the app can run without additional ingestion steps.
- Add a repository description, topics, and a proper author/email in `pyproject.toml` before publishing.
