# FACTRADE RAG System Architecture

## Overview

The FACTRADE RAG System is designed as a production-ready, modular system with built-in quality assurance, auto-debugging, and auto-updating capabilities. This document provides a detailed overview of the system architecture.

## Core Components

### 1. RAG System (`src/rag_system.py`)

The central orchestrator that coordinates all other components.

**Responsibilities:**
- Document ingestion and processing
- Vector storage management
- Query processing and response generation
- Coordination of quality checks and debugging
- Auto-update lifecycle management

**Key Methods:**
- `add_documents()`: Ingest and process new documents
- `query()`: Process user queries and generate responses
- `run_integrity_check()`: Execute comprehensive integrity validation
- `start_auto_update()`: Enable file monitoring
- `get_health_status()`: System health monitoring

**Dependencies:**
- LangChain for document processing and LLM integration
- ChromaDB for vector storage
- OpenAI for embeddings and LLM

### 2. Integrity Checker (`src/integrity_checker.py`)

Ensures data integrity throughout the system lifecycle.

**Responsibilities:**
- Validate embedding quality (dimensions, NaN, infinity)
- Detect duplicate documents
- Verify metadata completeness
- Identify orphaned documents
- Auto-fix common issues

**Quality Checks:**

**Embedding Validation:**
```python
- Dimension verification (must match config)
- NaN value detection
- Infinity value detection
- Zero magnitude detection
```

**Duplicate Detection:**
```python
- Hash-based content comparison
- Document ID tracking
- Automatic deduplication
```

**Metadata Verification:**
```python
- Required field validation (source, created_at)
- Source path validation
- Metadata completeness checks
```

**Orphan Detection:**
```python
- Cross-reference vector store vs document list
- Identify documents in store but not in list
- Identify documents in list but not in store
```

### 3. Quality Checker (`src/quality_checker.py`)

Validates the quality of retrieval and response generation.

**Responsibilities:**
- Retrieval quality assessment
- Response quality validation
- Performance monitoring
- Hallucination detection

**Quality Dimensions:**

**Retrieval Quality:**
```python
- Similarity score validation
- Retrieval time monitoring
- Relevance threshold enforcement
- Term overlap analysis
```

**Response Quality:**
```python
- Length validation (min/max bounds)
- Hallucination detection (grounding in sources)
- Source verification
- Coherence analysis
- Toxicity checking
```

**Performance Metrics:**
```python
- Query time (end-to-end)
- Embedding generation time
- Memory usage
- Throughput
```

### 4. Auto-Debugger (`src/auto_debugger.py`)

Provides self-healing and monitoring capabilities.

**Responsibilities:**
- Error handling and recovery
- Performance profiling
- Health monitoring
- Memory leak detection
- Self-healing operations

**Features:**

**Circuit Breaker:**
```python
class CircuitBreaker:
    - Tracks failure rates
    - Opens circuit after threshold
    - Half-open state for recovery
    - Automatic circuit closing
```

**Retry Mechanism:**
```python
- Exponential backoff
- Configurable max attempts
- Error logging
- Failure tracking
```

**Health Monitoring:**
```python
- CPU usage tracking
- Memory monitoring
- Disk space checking
- Error rate analysis
```

**Performance Profiling:**
```python
- Operation timing
- Memory delta tracking
- Metric aggregation
- Percentile calculations
```

### 5. Auto-Updater (`src/auto_updater.py`)

Manages automatic document updates and versioning.

**Responsibilities:**
- File system monitoring
- Incremental document updates
- Version management
- Scheduled reindexing

**Features:**

**File Monitoring:**
```python
class DocumentChangeHandler:
    - Real-time file system events
    - Created/Modified/Deleted detection
    - Batch change processing
    - Debounce logic
```

**Update Strategy:**
```python
- Hash-based change detection
- Incremental updates
- Batch processing
- Full reindexing support
```

**Versioning:**
```python
- Automatic snapshots
- Version history tracking
- Rollback capability
- Configurable retention
```

### 6. Configuration Manager (`src/config_manager.py`)

Centralized configuration management with validation.

**Responsibilities:**
- Configuration loading and validation
- Environment setup
- Configuration reloading
- Default value management

**Configuration Structure:**
```python
Config (Pydantic Model)
├── System
├── VectorStore
├── Embeddings
├── LLM
├── DocumentProcessing
├── Retrieval
├── QualityChecks
│   ├── Integrity
│   ├── Retrieval
│   ├── Response
│   └── Performance
├── AutoDebugger
│   ├── ErrorHandling
│   ├── Monitoring
│   ├── Logging
│   └── SelfHealing
└── AutoUpdate
    ├── SourceMonitoring
    ├── UpdateStrategy
    └── Versioning
```

### 7. Logger (`src/logger.py`)

Structured logging system with multiple outputs.

**Features:**
- Structured JSON logging
- Multiple log levels
- Rotating file handlers
- Separate error logs
- Console output

## Data Flow

### Document Ingestion Flow

```
1. User adds documents
   │
   ↓
2. RAGSystem.add_documents()
   │
   ├─→ Load document (PDF, DOCX, etc.)
   │
   ├─→ Split into chunks (RecursiveCharacterTextSplitter)
   │
   ├─→ Generate embeddings (OpenAI)
   │
   ├─→ Store in vector DB (ChromaDB)
   │
   └─→ Update document index
```

### Query Processing Flow

```
1. User submits query
   │
   ↓
2. Track query pattern (Auto-Debugger)
   │
   ↓
3. Generate query embedding
   │
   ↓
4. Retrieve similar documents
   │   ├─→ Check retrieval quality
   │   └─→ Monitor retrieval time
   │
   ↓
5. Generate response (LLM)
   │   ├─→ Check response quality
   │   ├─→ Detect hallucination
   │   └─→ Verify sources
   │
   ↓
6. Check performance metrics
   │
   ↓
7. Return result with metrics
```

### Auto-Update Flow

```
1. File system event detected
   │
   ↓
2. Event handler accumulates changes
   │
   ↓
3. After debounce period
   │
   ↓
4. Process changes
   │
   ├─→ Created files: Add to system
   │
   ├─→ Modified files: Update in system
   │    ├─→ Calculate file hash
   │    ├─→ Compare with index
   │    └─→ Update if changed
   │
   └─→ Deleted files: Remove from system
   │
   ↓
5. Create version snapshot
   │
   ↓
6. Update document index
```

### Integrity Check Flow

```
1. Trigger integrity check
   │
   ↓
2. Validate embeddings
   │   ├─→ Check dimensions
   │   ├─→ Detect NaN/Inf
   │   └─→ Verify magnitude
   │
   ↓
3. Check for duplicates
   │   ├─→ Hash content
   │   └─→ Identify duplicates
   │
   ↓
4. Verify metadata
   │   ├─→ Check required fields
   │   └─→ Validate values
   │
   ↓
5. Detect orphaned documents
   │   ├─→ Compare store vs index
   │   └─→ Identify mismatches
   │
   ↓
6. Auto-fix issues (if enabled)
   │   ├─→ Remove duplicates
   │   └─→ Clean orphans
   │
   ↓
7. Return results
```

## Error Handling Strategy

### Layered Error Handling

```
Level 1: Retry with Exponential Backoff
├─→ Transient errors (network, timeout)
├─→ Max 3 attempts
└─→ Backoff: 2^attempt seconds

Level 2: Circuit Breaker
├─→ Persistent failures
├─→ Opens after 5 failures
└─→ 60 second timeout

Level 3: Self-Healing
├─→ Memory errors → garbage collection
├─→ Connection errors → wait and retry
└─→ Cache errors → invalidate cache

Level 4: Graceful Degradation
├─→ Disable non-critical features
└─→ Return partial results
```

## Performance Optimization

### Caching Strategy

```
Embedding Cache
├─→ Cache embeddings by content hash
├─→ TTL: 1 hour
├─→ Max size: 512 MB
└─→ Invalidation on document update

Vector Store Persistence
├─→ Disk-backed storage
├─→ Lazy loading
└─→ Periodic optimization
```

### Batch Processing

```
Document Processing
├─→ Batch size: 50 documents
├─→ Parallel embedding generation
└─→ Bulk vector store insertion

Query Processing
├─→ Top-K retrieval (default: 5)
├─→ Reranking enabled
└─→ Hybrid search (semantic + keyword)
```

## Scalability Considerations

### Horizontal Scaling

- API server can be replicated
- Load balancer distributes requests
- Shared vector store backend
- Centralized logging and metrics

### Vertical Scaling

- Adjustable chunk size
- Configurable batch sizes
- Memory limits
- Resource pooling

## Security Considerations

### API Security

- CORS configuration
- Rate limiting (60 req/min)
- Input validation
- Authentication support (configurable)

### Data Security

- Encryption at rest (vector store)
- Secure API key management
- Audit logging
- Access control

## Monitoring and Observability

### Metrics Collection

```
System Metrics
├─→ CPU usage
├─→ Memory usage
├─→ Disk usage
└─→ Error rates

Application Metrics
├─→ Query latency
├─→ Retrieval time
├─→ Embedding time
├─→ Document count
└─→ Quality check results

Business Metrics
├─→ Query patterns
├─→ User satisfaction (implicit)
└─→ System uptime
```

### Log Aggregation

```
Structured Logs
├─→ Timestamp
├─→ Log level
├─→ Operation
├─→ Context
└─→ Metrics

Log Destinations
├─→ Console (development)
├─→ File (production)
└─→ External aggregator (optional)
```

## Deployment Architecture

### Development

```
┌─────────────┐
│  Developer  │
└──────┬──────┘
       │
       ↓
┌─────────────┐
│  RAG System │
│   (CLI)     │
└─────────────┘
```

### Production

```
┌──────────┐
│  Client  │
└────┬─────┘
     │
     ↓
┌────────────┐
│    API     │
│  Gateway   │
└─────┬──────┘
      │
      ↓
┌─────────────────┐
│  Load Balancer  │
└────┬───────┬────┘
     │       │
     ↓       ↓
┌─────┐   ┌─────┐
│ API │   │ API │
│  1  │   │  2  │
└──┬──┘   └──┬──┘
   │         │
   └────┬────┘
        │
        ↓
┌───────────────┐
│  Vector Store │
│   (ChromaDB)  │
└───────────────┘
```

## Extension Points

### Custom Document Loaders

```python
from langchain.document_loaders.base import BaseLoader

class CustomLoader(BaseLoader):
    def load(self):
        # Custom loading logic
        pass
```

### Custom Quality Checks

```python
class CustomQualityChecker:
    def check_custom_metric(self, data):
        # Custom validation logic
        pass
```

### Custom Embeddings

```python
from langchain.embeddings.base import Embeddings

class CustomEmbeddings(Embeddings):
    def embed_documents(self, texts):
        # Custom embedding logic
        pass
```

## Future Enhancements

1. **Multi-tenancy**: Support for multiple isolated RAG instances
2. **Advanced Reranking**: Cross-encoder based reranking
3. **Hybrid Search**: BM25 + Semantic search
4. **Streaming Responses**: Server-sent events for real-time responses
5. **Analytics Dashboard**: Real-time metrics visualization
6. **Plugin System**: Extensible architecture for custom components
