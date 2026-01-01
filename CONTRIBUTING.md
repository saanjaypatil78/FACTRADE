# Contributing to FACTRADE RAG System

Thank you for your interest in contributing to the FACTRADE RAG System! This document provides guidelines and instructions for contributing.

## Code of Conduct

- Be respectful and inclusive
- Provide constructive feedback
- Focus on what is best for the community
- Show empathy towards other community members

## Getting Started

### Prerequisites

- Python 3.9 or higher
- Git
- Basic understanding of RAG systems
- Familiarity with LangChain and vector databases

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/your-username/FACTRADE.git
   cd FACTRADE
   ```

3. Create a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Set up environment variables:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

6. Run tests to verify setup:
   ```bash
   pytest
   ```

## Development Workflow

### Creating a Feature Branch

```bash
git checkout -b feature/your-feature-name
```

Branch naming conventions:
- `feature/` - New features
- `bugfix/` - Bug fixes
- `docs/` - Documentation updates
- `refactor/` - Code refactoring
- `test/` - Test additions or modifications

### Making Changes

1. Write your code following the style guide
2. Add tests for new functionality
3. Update documentation as needed
4. Ensure all tests pass
5. Commit your changes with clear messages

### Commit Messages

Follow the conventional commits format:

```
type(scope): subject

body

footer
```

Types:
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Test additions or modifications
- `chore`: Maintenance tasks

Example:
```
feat(quality-checker): add advanced hallucination detection

Implemented NLI-based hallucination detection using cross-encoder
models for improved accuracy in detecting unfaithful responses.

Closes #123
```

### Code Style

- Follow PEP 8 guidelines
- Use type hints for function parameters and returns
- Write docstrings for classes and functions
- Keep functions focused and concise
- Use meaningful variable names

Example:
```python
def check_retrieval_quality(
    self,
    query: str,
    retrieved_docs: List[Dict[str, Any]],
    retrieval_time_ms: float
) -> Dict[str, Any]:
    """
    Check the quality of retrieved documents.
    
    Args:
        query: The user's query
        retrieved_docs: List of retrieved documents
        retrieval_time_ms: Time taken for retrieval
        
    Returns:
        Dictionary containing quality check results
    """
    # Implementation
    pass
```

### Testing

#### Writing Tests

- Write tests for all new functionality
- Follow the AAA pattern (Arrange, Act, Assert)
- Use descriptive test names
- Mock external dependencies
- Test edge cases and error conditions

Example:
```python
def test_check_retrieval_quality_with_valid_data():
    # Arrange
    quality_checker = QualityChecker(config)
    query = "What is machine learning?"
    retrieved_docs = [{"content": "ML is...", "score": 0.9}]
    
    # Act
    result = quality_checker.check_retrieval_quality(
        query, retrieved_docs, 100
    )
    
    # Assert
    assert result['passed'] is True
    assert 'checks' in result
```

#### Running Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_quality_checker.py

# Run with coverage
pytest --cov=src tests/

# Run only unit tests
pytest -m unit
```

### Documentation

- Update README.md for user-facing changes
- Update ARCHITECTURE.md for architectural changes
- Add docstrings to all public functions and classes
- Include examples in docstrings
- Keep documentation up to date with code changes

## Pull Request Process

### Before Submitting

1. Ensure all tests pass
2. Update documentation
3. Add tests for new features
4. Follow the code style guide
5. Rebase on the latest main branch

### Submitting a Pull Request

1. Push your branch to your fork
2. Create a pull request from your branch to `main`
3. Fill out the pull request template
4. Link related issues
5. Request review from maintainers

### Pull Request Template

```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] All tests pass
- [ ] New tests added
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated
- [ ] No new warnings
```

### Review Process

- Maintainers will review your PR
- Address feedback and comments
- Make requested changes
- Update PR with additional commits
- Once approved, PR will be merged

## Areas for Contribution

### High Priority

- Additional embedding providers (Cohere, Anthropic)
- Advanced hallucination detection
- Multi-modal support (images, tables)
- Distributed vector store support
- Performance optimizations

### Medium Priority

- Additional document loaders
- Custom reranking strategies
- Advanced analytics dashboard
- Plugin system
- Integration tests

### Low Priority

- UI improvements
- Additional examples
- Documentation enhancements
- Code cleanup

## Getting Help

- Create an issue for bugs or feature requests
- Tag maintainers for urgent issues
- Join community discussions
- Check existing documentation

## Recognition

Contributors will be:
- Added to CONTRIBUTORS.md
- Mentioned in release notes
- Acknowledged in documentation

Thank you for contributing!
