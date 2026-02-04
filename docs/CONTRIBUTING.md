# Contributing to KVM Serial

Firstly, thank you for taking the time to contribute! I really appreciate it. ❤️

This guide outlines how to contribute to the KVM Serial project, and helps ensure a smooth experience for everyone involved.

If this project has been useful to you, please consider giving it a star. ⭐️

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [I Have a Question](#i-have-a-question)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [How to Contribute](#how-to-contribute)
- [Reporting Bugs](#reporting-bugs)
- [Pull Requests](#pull-requests)
- [Testing](#testing)
- [Documentation](#documentation)

## Code of Conduct

This project is committed to providing a welcoming and inclusive environment for all contributors. In summary: be decent to others in this space, act in good faith and assume good faith on others' parts, and conduct onself in a way which would be acceptable in the workplace.

All participants should:

- Be respectful and considerate in communications
- Show empathy towards other community members
- Accept constructive criticism gracefully
- Focus on what is best for the project

Unacceptable behavior includes:

- Any conduct that would be inappropriate in a professional setting
- Harassment of any kind
- Discriminatory jokes and language
- Personal or political attacks
- Publishing others' private information
- Trolling or insulting comments

Violations should be reported to the project maintainer(s), who will take appropriate action.

## I Have a Question

Before asking a question:

1. Read the [Home](index.md) page and any available documentation
2. Search existing [Issues](https://github.com/sjmf/kvm-serial/issues) to see if your question has already been answered
3. Search the internet for answers first: putting errors from the console into a search engine is a great place to start.

If you still need clarification, please:

- Open a [new issue](https://github.com/sjmf/kvm-serial/issues/new)
- Provide as much context as possible: issues saying "it doesn't work", without further detail, will be closed saying "yes, it does".
- Include relevant system information (OS, Python version, hardware details)

## Getting Started

### Forking the Repository

You will need to fork the repository if you want to contribute via [Pull Request](#pull-requests).
If that's you, read on!

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/your-username/kvm-serial.git
   cd kvm-serial
   ```
3. Add the canonical repository to pull upstream changes:
   ```bash
   git remote add upstream https://github.com/sjmf/kvm-serial.git
   ```

## Development Setup

To develop the code, there's a few steps to get set up:

1. **Python Environment**: Ensure you have Python 3.8+ installed
2. **Install Dependencies and Dev Dependencies**:
   ```bash
   pip install -e .
   pip install '.[dev]'
   ```
3. **Install Pre-commit Hooks**: 
   ```bash
   pre-commit install
   pre-commit run --all-files  # Run pre-commit on all files (optional)
   ```

Pre-commit hooks help to ensure that any code contributed follows the code style (`black`).

## How to Contribute

Contributions are fab! I really appreciate your being interested in this project. A contribution might be a bug report, a suggestion for a feature enhancement, addressing an oversight in the documentation or test suite, or just a well-structured question about how to use this project e.g. in a way we've not seen before.

If you're considering giving back in the form of a contribution, here's the best way to do that:

### Reporting Bugs

#### Before Submitting a Bug Report

Please ensure you're using the latest version of the software and verify that the issue is actually a bug rather than a configuration problem or user error. Search through existing [bug reports](https://github.com/sjmf/kvm-serial/issues?q=is%3Aissue+label%3Abug) to see if someone else has already encountered the same problem.

When preparing your bug report, collect comprehensive information about your system environment. This should include your Python version and operating system, details about your hardware setup (particularly the CH9329 device and any connected cameras), your serial port configuration, complete error messages with stack traces, and clear steps that reliably reproduce the issue.

#### How to Submit a Bug Report

Open a [new issue](https://github.com/sjmf/kvm-serial/issues/new) with a clear, descriptive title that summarizes the problem. Describe both what behavior you expected to see and what actually happened. The most valuable bug reports include step-by-step reproduction instructions that allow maintainers to recreate the issue on their own systems. Include all the system and configuration information you collected, as this context is often crucial for diagnosing the root cause.

### Pull Requests

#### Before Creating a Pull Request

1. **Create an Issue First**: For significant changes, create an issue to discuss the approach
2. **Fork and Branch**: Create a feature branch from `main`
3. **Stay Updated**: Regularly sync with upstream:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

#### Pull Request Guidelines

1. **One Change Per PR**: Submit separate PRs for different features/fixes
2. **Clear Description**: Explain what your PR does and why
3. **Reference Issues**: Link to related issues with "Fixes #123"
4. **Test Your Changes**: Ensure all tests pass
5. **Follow Code Standards**: Use pre-commit hooks and linting

### Commit Message Guidelines

Examples:

- `feat(video): add support for USB 3.0 cameras`
- `fix(serial): handle port disconnection gracefully`
- `docs(readme): update installation instructions`

## Testing

### Running Tests

```bash
# Run all tests
python -m pytest

# Run with coverage
python -m pytest --cov=kvm_serial

# Run specific test categories, e.g.:
python -m pytest tests/kvm
python -m pytest tests/backend
```

### Writing Tests

Tests should be placed in the `tests/` directory. When writing new tests, focus on covering both successful operations and error conditions, ensuring that external dependencies like hardware devices are properly mocked to prevent actual device access during testing.

Follow established patterns in the existing test suite, particularly around the use of context managers for patching and the helper methods provided by the base test class. The test structure emphasizes isolation and repeatability, so each test should be able to run independently without relying on state from other tests.

Always check that tests pass in concert with other tests: tests can modify the global import state of the test environment, which can result in interference for example where a test accidentally makes an import which can then no longer be patched. I've gone to some lengths to check that tests don't interfere with each other (or skip them where they do), but it's far too easy to write a test where this can occur!

## Documentation

Documentation improvements are always welcome. Good documentation contributions focus on the user experience, and often come from people who have recently worked through setup or usage scenarios themselves.

When updating documentation, prioritise clarity and accuracy over comprehensiveness. Include practical examples where they help illustrate concepts, and always test any instructions or code examples you add to ensure they work as described. If you're documenting new features, consider including both basic usage examples and more advanced scenarios.

Documentation should be updated whenever functionality changes. This includes not just user-facing features, but also development processes, testing procedures, and troubleshooting information. The goal is to reduce friction for both users and future contributors.

## Legal Notice

By contributing to this project, you agree that:

- You have authored 100% of the contributed content
- You have the necessary rights to the content
- Your contribution may be provided under the project license

## Questions?

If you have questions about contributing, feel free to:

- Open an [issue](https://github.com/sjmf/kvm-serial/issues/new)
- Contact the maintainers

Thank you for contributing to KVM Serial! 🎉
