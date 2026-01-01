# FACTRADE RAG System

A production-ready, auto-updating Retrieval-Augmented Generation (RAG) system with built-in quality checks, auto-debugging capabilities, and integrity validation.

## Features

### Core RAG Capabilities
- **Document Processing**: Support for PDF, DOCX, TXT, MD, and HTML files
- **Vector Storage**: ChromaDB-based vector storage with persistence
- **Embeddings**: OpenAI embeddings with caching
- **LLM Integration**: OpenAI GPT-4 for response generation
- **Semantic Search**: Hybrid search combining semantic and keyword matching
- **Context-Aware Responses**: Source citation and context tracking

### Auto-Update System
- **File Monitoring**: Real-time detection of document changes using watchdog
- **Incremental Updates**: Efficient batch processing of document updates
- **Version Control**: Automatic versioning with rollback capabilities
- **Scheduled Reindexing**: Configurable cron-based full reindexing
- **Change Detection**: Hash-based duplicate detection and modification tracking

### Quality Check System
- **Data Integrity Checks**:
  - Embedding validation (dimension, NaN, infinity checks)
  - Duplicate document detection
  - Metadata verification
  - Orphaned document detection
  
- **Retrieval Quality Checks**:
  - Similarity score validation
  - Retrieval time monitoring
  - Relevance threshold enforcement
  
- **Response Quality Checks**:
  - Hallucination detection
  - Source verification
  - Coherence analysis
  - Toxicity checking
  - Response length validation
  
- **Performance Benchmarks**:
  - Query time tracking
  - Memory usage monitoring
  - Embedding generation time
  - Uptime tracking

### Auto-Debugger
- **Error Handling**:
  - Automatic retry with exponential backoff
  - Circuit breaker pattern for fault isolation
  - Comprehensive error logging and tracking
  
- **Monitoring**:
  - Real-time health checks
  - Performance profiling
  - Memory leak detection
  - Query pattern analysis
  
- **Self-Healing**:
  - Automatic recovery from failures
  - Cache invalidation
  - Index optimization
  - Orphaned process cleanup

## Installation

### Prerequisites
- Python 3.9 or higher
- OpenAI API key

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd FACTRADE
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables:
```bash
export OPENAI_API_KEY="your-api-key-here"
```

5. Configure the system (optional):
Edit `config.yaml` to customize settings.

## Usage

### API Server Mode

Start the REST API server:
```bash
python main.py --mode api
```

The API will be available at `http://localhost:8000`

#### API Endpoints

**Query the System**
```bash
POST /query
{
  "question": "What is machine learning?"
}
```

**Add Documents**
```bash
POST /documents/add
{
  "file_paths": ["./data/documents/doc1.pdf", "./data/documents/doc2.txt"]
}
```

**Delete Document**
```bash
DELETE /documents/source/{source_path}
```

**Health Check**
```bash
GET /health
```

**Statistics**
```bash
GET /statistics
```

**Integrity Check**
```bash
GET /integrity-check
```

**Performance Summary**
```bash
GET /performance-summary?operation=query
```

**Error Summary**
```bash
GET /error-summary?last_n_minutes=60
```

**Query Patterns**
```bash
GET /query-patterns
```

**Memory Leak Check**
```bash
GET /memory-leak-check
```

**Force Reindex**
```bash
POST /reindex
```

### CLI Mode

**Interactive Mode**
```bash
python main.py --mode cli
```

**Add Documents**
```bash
python main.py --mode cli --add-documents ./data/documents/doc1.pdf ./data/documents/doc2.txt
```

**Query**
```bash
python main.py --mode cli --query "What is the main topic of the documents?"
```

**Integrity Check**
```bash
python main.py --mode cli --integrity-check
```

**Force Reindex**
```bash
python main.py --mode cli --reindex
```

### Python API

```python
from src.rag_system import RAGSystem

# Initialize the system
rag = RAGSystem()

# Add documents
rag.add_documents(["./data/documents/doc1.pdf"])

# Query
result = rag.query("What is machine learning?")
print(result["answer"])

# Start auto-update monitoring
rag.start_auto_update()

# Run integrity check
integrity_results = rag.run_integrity_check()

# Get health status
health = rag.get_health_status()

# Get performance metrics
performance = rag.get_performance_summary()

# Stop auto-update
rag.stop_auto_update()
```

## Configuration

The system is configured via `config.yaml`. Key configuration sections:

### System Configuration
```yaml
system:
  name: "FACTRADE RAG System"
  version: "1.0.0"
  environment: "development"
```

### Vector Store Configuration
```yaml
vector_store:
  type: "chromadb"
  persist_directory: "./data/vector_store"
  collection_name: "factrade_knowledge"
  distance_metric: "cosine"
```

### Embeddings Configuration
```yaml
embeddings:
  provider: "openai"
  model: "text-embedding-3-small"
  dimension: 1536
  batch_size: 100
  cache_enabled: true
```

### Quality Checks Configuration
```yaml
quality_checks:
  enabled: true
  integrity:
    validate_embeddings: true
    check_duplicates: true
    verify_metadata: true
  retrieval:
    min_similarity_score: 0.6
    max_retrieval_time_ms: 500
  response:
    check_hallucination: true
    verify_sources: true
    toxicity_check: true
```

### Auto-Debugger Configuration
```yaml
auto_debugger:
  enabled: true
  error_handling:
    auto_recovery: true
    max_retry_attempts: 3
  monitoring:
    health_check_interval_seconds: 60
    performance_profiling: true
    memory_leak_detection: true
  self_healing:
    enabled: true
    auto_optimize_indices: true
```

### Auto-Update Configuration
```yaml
auto_update:
  enabled: true
  monitoring:
    watch_directories: ["./data/documents"]
    watch_interval_seconds: 300
  strategy:
    incremental_updates: true
    batch_size: 50
    update_schedule: "0 2 * * *"
  versioning:
    enabled: true
    max_versions: 10
```

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        RAG System                           │
├─────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │   Document    │  │   Vector     │  │   LLM/          │ │
│  │   Processor   │─▶│   Store      │─▶│   Retriever     │ │
│  └───────────────┘  └──────────────┘  └─────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
┌───────▼────────┐  ┌───────▼───────┐  ┌───────▼────────┐
│   Integrity    │  │    Quality    │  │  Auto-Debugger │
│    Checker     │  │    Checker    │  │                │
├────────────────┤  ├───────────────┤  ├────────────────┤
│ • Embedding    │  │ • Retrieval   │  │ • Circuit      │
│   Validation   │  │   Quality     │  │   Breaker      │
│ • Duplicate    │  │ • Response    │  │ • Retry Logic  │
│   Detection    │  │   Quality     │  │ • Health Check │
│ • Metadata     │  │ • Performance │  │ • Profiling    │
│   Verification │  │   Monitoring  │  │ • Self-Healing │
└────────────────┘  └───────────────┘  └────────────────┘
                            ▲
                            │
                    ┌───────▼────────┐
                    │  Auto-Updater  │
                    ├────────────────┤
                    │ • File Watch   │
                    │ • Incremental  │
                    │   Updates      │
                    │ • Versioning   │
                    │ • Scheduling   │
                    └────────────────┘
```

### Data Flow

1. **Document Ingestion**:
   - Documents are loaded and split into chunks
   - Embeddings are generated for each chunk
   - Chunks are stored in the vector database

2. **Query Processing**:
   - Query is embedded
   - Similar documents are retrieved
   - Context is passed to LLM
   - Response is generated with sources

3. **Quality Assurance**:
   - Retrieval quality is checked
   - Response quality is validated
   - Performance is monitored
   - Issues are logged

4. **Auto-Update**:
   - File system is monitored
   - Changes are detected
   - Documents are incrementally updated
   - Versions are maintained

## Testing

Run all tests:
```bash
python main.py --mode test
```

Run specific test file:
```bash
pytest tests/test_integrity_checker.py -v
```

Run with coverage:
```bash
pytest --cov=src tests/
```

## Monitoring and Observability

### Logging

Logs are stored in `./logs/`:
- `rag_system.log`: All system logs
- `errors.log`: Error-only logs

Logs are structured JSON for easy parsing and analysis.

### Metrics

Prometheus metrics are exposed on port 9090 (configurable):
- Query latency
- Error rates
- Memory usage
- Document counts
- Quality check results

### Health Checks

Health endpoint provides:
- System status (healthy/degraded/critical)
- CPU usage
- Memory usage
- Disk usage
- Recent error count

## Performance

### Benchmarks

Typical performance on standard hardware:
- Query latency: 500-2000ms
- Embedding generation: 100-500ms per document
- Retrieval time: 50-200ms
- Memory usage: 500-2000MB

### Optimization Tips

1. **Batch Processing**: Enable batch updates for large document sets
2. **Caching**: Enable embedding cache for frequently accessed documents
3. **Chunk Size**: Adjust chunk size based on document types
4. **Index Optimization**: Run regular reindexing during off-peak hours
5. **Resource Limits**: Configure memory and CPU limits appropriately

## Troubleshooting

### Common Issues

**High Memory Usage**
- Reduce batch size
- Enable cache cleanup
- Run periodic reindexing

**Slow Query Times**
- Reduce `top_k` in retrieval
- Optimize chunk size
- Check embedding cache

**Quality Check Failures**
- Review similarity thresholds
- Adjust coherence requirements
- Check source documents

**Auto-Update Not Working**
- Verify watch directories exist
- Check file permissions
- Review logs for errors

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch
3. Add tests for new features
4. Ensure all tests pass
5. Submit a pull request

## License

[Add your license here]

## Support

For issues and questions:
- Create an issue on GitHub
- Check the documentation
- Review logs for error details

## Roadmap

- [ ] Support for additional embedding providers
- [ ] Advanced hallucination detection with NLI models
- [ ] Multi-modal document support (images, tables)
- [ ] Distributed vector store support
- [ ] Real-time collaboration features
- [ ] Advanced analytics dashboard
- [ ] Plugin system for custom processors
