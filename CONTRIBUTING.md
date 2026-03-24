# Contributing to RTG

Thanks for contributing.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Development Workflow

1. Create a branch from `main`.
2. Keep changes focused and easy to review.
3. Run tests before opening a pull request.
4. Include screenshots for UI changes when helpful.

## Tests

```powershell
pytest -q
```

## Notes

- Avoid committing local databases, exports, or temporary build artifacts.
- Keep the dashboard behavior consistent across English and Chinese views.
- If scraper behavior changes, update tests in `tests/`.
