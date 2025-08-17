# Contributing

Thanks for considering contributing!

Guidelines

- Open an issue to discuss large changes before starting work.
- Follow the project's coding style; keep commits small and focused.
- Write tests for new functionality where practical.
- Update the `README.md` with usage or API changes.

How to run locally

1. Create and activate a virtual environment:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1

2. Install dependencies:

    pip install -r requirements.txt

3. Run a quick smoke test:

    python -c "import app; print('imported app')"

Pull requests

- Use feature branches and set the PR base to `main` (or your default branch).
- Include a brief description of the change and related issue number.
- Maintain a clean commit history; rebase if needed.
