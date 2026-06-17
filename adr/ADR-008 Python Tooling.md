## ADR-008 Python Tooling

### Decision:

Python applications in this project should be,
- Managed using poetry
- Implemented as modules with a wrapping CLI
- The CLI should implement a help function that returns a brief message about the the tool and argument help when invokes without options
- Each python application project should be setup with ruff to perform both static analysis and formatting after each change
- Each python application project use pytest as its test harness

### Impacts

This impacts the project tooling used for python applications across the project's repositories. This decision does *not* impact applications implemented using other tools (ex: javascript, bash, etc).

### Reasoning

We want to standardize the tool suite used for python project dependency management, testing (both unit and functional), static analysis, and code formatting. Standardizing these tools enables the same agent instructions and CI/CD tooling to be used across several project repositories.