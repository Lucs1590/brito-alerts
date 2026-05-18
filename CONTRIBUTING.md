# Contributing to Brito Alerts

First, thank you for being interested in contributing to Brito Alerts! This document provides guidelines and instructions for contributing.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:

   ```bash
   git clone https://github.com/YOUR_USERNAME/brito-alerts.git
   cd brito-alerts
   ```

3. **Set up development environment**:

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   pip install -e ".[dev]"  # Install with development dependencies
   ```

4. **Create a branch** for your changes:

   ```bash
   git checkout -b feature/your-feature-name
   ```

## Development Workflow

### Running Tests

```bash
pytest
pytest --cov=src  # With coverage report
```

### Code Style

We follow PEP 8 style guidelines. Format your code with:

```bash
black src/
ruff check src/ --fix
```

### Type Checking

```bash
mypy src/
```

### Pre-commit Hooks

```bash
pre-commit install
pre-commit run --all-files
```

## Submitting Changes

1. **Make your changes** with clear, focused commits
2. **Write tests** for new functionality
3. **Update documentation** if needed
4. **Push to your fork**:

   ```bash
   git push origin feature/your-feature-name
   ```

5. **Create a Pull Request** on GitHub with:
   - Clear title and description
   - Reference to any related issues
   - Tests for new functionality
   - Updated documentation

## Pull Request Guidelines

- One feature/fix per pull request
- Include tests with sufficient coverage
- Follow the existing code style
- Update relevant documentation
- Keep commits clean and descriptive

## Code of Conduct

Be respectful and inclusive. We welcome contributors from all backgrounds and experience levels.

## Questions?

Feel free to open an issue or discussion if you have questions about how to contribute.

Thank you for your contributions!
