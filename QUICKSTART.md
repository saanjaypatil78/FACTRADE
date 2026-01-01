# Quick Start Guide

Get started with the FACTRADE RAG System in 5 minutes.

## Prerequisites

- Python 3.9 or higher
- OpenAI API key

## Installation

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and add your OpenAI API key:

```
OPENAI_API_KEY=sk-your-key-here
```

### 3. Verify Installation

Check that everything is set up correctly:

```bash
python main.py --mode cli --help
```

## Basic Usage

### Start the API Server

```bash
python main.py --mode api
```

The API will be available at http://localhost:8000

Test the API:

```bash
curl http://localhost:8000/
```

### Use the CLI

#### Add Documents

```bash
python main.py --mode cli --add-documents ./data/documents/sample.txt
```

#### Query the System

```bash
python main.py --mode cli --query "What is FACTRADE?"
```

#### Interactive Mode

```bash
python main.py --mode cli
```

Then type your questions and press Enter.

### Use the API

#### Query Endpoint

```bash
curl -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"question": "What is FACTRADE?"}'
```

#### Add Documents

```bash
curl -X POST "http://localhost:8000/documents/add" \
  -H "Content-Type: application/json" \
  -d '{"file_paths": ["./data/documents/sample.txt"]}'
```

#### Health Check

```bash
curl http://localhost:8000/health
```

#### Statistics

```bash
curl http://localhost:8000/statistics
```

## Python API Usage

```python
from src.rag_system import RAGSystem

# Initialize
rag = RAGSystem()

# Add documents
rag.add_documents(["./data/documents/sample.txt"])

# Query
result = rag.query("What is FACTRADE?")
print(result["answer"])

# Start auto-update
rag.start_auto_update()

# Your application code here...

# Stop auto-update when done
rag.stop_auto_update()
```

## Configuration

Edit `config.yaml` to customize:

```yaml
# Change LLM model
llm:
  model: "gpt-4-turbo-preview"  # or "gpt-3.5-turbo"
  temperature: 0.7

# Adjust chunk size
document_processing:
  chunk_size: 1000
  chunk_overlap: 200

# Enable/disable features
quality_checks:
  enabled: true

auto_update:
  enabled: true
```

## Common Tasks

### Add Multiple Documents

```bash
python main.py --mode cli --add-documents \
  ./data/documents/doc1.pdf \
  ./data/documents/doc2.txt \
  ./data/documents/doc3.md
```

### Run Integrity Check

```bash
python main.py --mode cli --integrity-check
```

### Force Reindex

```bash
python main.py --mode cli --reindex
```

### Check System Health

```bash
curl http://localhost:8000/health
```

### View Performance Metrics

```bash
curl http://localhost:8000/performance-summary
```

### Check for Memory Leaks

```bash
curl http://localhost:8000/memory-leak-check
```

## Monitoring

### Logs

Logs are stored in `./logs/`:
- `rag_system.log` - All system logs
- `errors.log` - Errors only

View logs:

```bash
tail -f logs/rag_system.log
```

### Metrics

Access metrics at:
- Health: http://localhost:8000/health
- Statistics: http://localhost:8000/statistics
- Performance: http://localhost:8000/performance-summary

## Troubleshooting

### "Module not found" errors

Install dependencies:

```bash
pip install -r requirements.txt
```

### "OPENAI_API_KEY not set" error

Set the environment variable:

```bash
export OPENAI_API_KEY="sk-your-key-here"
```

Or add it to your `.env` file.

### No documents found

Make sure documents are in the watch directory:

```bash
mkdir -p data/documents
cp your-document.pdf data/documents/
```

### Slow queries

Adjust configuration:

```yaml
retrieval:
  top_k: 3  # Reduce from 5

document_processing:
  chunk_size: 500  # Reduce from 1000
```

### High memory usage

Configure limits:

```yaml
quality_checks:
  performance:
    max_memory_usage_mb: 1024  # Adjust as needed
```

## Next Steps

- Read the [README](README.md) for detailed documentation
- Check the [Architecture](ARCHITECTURE.md) document
- Review [Contributing Guidelines](CONTRIBUTING.md)
- Explore the API documentation at http://localhost:8000/docs

## Getting Help

- Check logs in `./logs/`
- Review error messages carefully
- Consult the documentation
- Create an issue on GitHub

## Example Workflow

Here's a complete example workflow:

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
export OPENAI_API_KEY="sk-your-key-here"

# 3. Add some documents
mkdir -p data/documents
echo "Machine learning is awesome!" > data/documents/ml.txt

# 4. Start the system
python main.py --mode cli

# 5. Add documents
>>> (in CLI) Will auto-detect documents in data/documents/

# 6. Ask questions
>>> What is machine learning?
>>> (Get answer with sources)

# 7. Check integrity
>>> (Exit CLI and run)
python main.py --mode cli --integrity-check

# 8. Start API server for production
python main.py --mode api
```

That's it! You're now ready to use the FACTRADE RAG System.
