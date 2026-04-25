# Global Coding Rules

These rules apply to all code generated or modified by Antigravity in this repository.

## 1. Clean Code & Architecture
- **DRY (Don't Repeat Yourself)**: Abstract common logic into utilities or services.
- **KISS (Keep It Simple, Stupid)**: Favor clarity over cleverness.
- **SOLID Principles**: Especially Single Responsibility and Dependency Inversion.
- **Dependency Injection**: Pass dependencies through constructors. Avoid global state or direct instantiation of services inside other services.
- **Protocol-based Abstractions**: Use `Protocol` (Python) or Interfaces (TS) to define contracts.

## 2. Naming Conventions
- **Files**: Use `snake_case` for Python files, `kebab-case` for documentation/assets.
- **Variables/Functions**: Use `snake_case` in Python.
- **Classes**: Use `PascalCase`.
- **Constants**: Use `SCREAMING_SNAKE_CASE`.

## 3. Error Handling
- **Exceptions**: Use domain-specific exceptions (defined in `exceptions.py`).
- **Graceful Failure**: Always handle potential failures (network, file system, LLM timeouts) and log appropriately.
- **No Silent Errors**: Never use `pass` in an `except` block without logging or a very good reason.

## 4. Documentation & Comments
- **Docstrings**: All public methods and classes must have docstrings.
- **Why, not What**: Comments should explain *why* something is done if it's not obvious. Don't state the obvious.
- **Type Hints**: Mandatory for all function signatures and variable declarations where possible.

## 5. Security & Credentials
- **Environment Variables**: Never hardcode secrets. Use `.env` and `config.py`.
- **Validation**: Use Pydantic for configuration and data validation.
