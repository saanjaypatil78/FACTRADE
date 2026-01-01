from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime
import structlog

from .rag_system import RAGSystem
from .config_manager import get_config
from .logger import setup_logging

logger = structlog.get_logger()


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=1000)
    options: Optional[Dict[str, Any]] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    quality_checks: Dict[str, Any]
    timestamp: str


class AddDocumentsRequest(BaseModel):
    file_paths: List[str]


class HealthResponse(BaseModel):
    status: str
    last_check: str
    issues: List[Dict[str, Any]]
    metrics: Optional[Dict[str, Any]] = None


class StatisticsResponse(BaseModel):
    total_documents: int
    total_chunks: int
    vector_store_type: str
    embedding_model: str
    llm_model: str
    auto_update_enabled: bool
    quality_checks_enabled: bool


def create_app() -> FastAPI:
    config = get_config()
    
    setup_logging(
        log_level=config.auto_debugger.logging.level,
        log_directory=config.auto_debugger.logging.log_directory,
        max_log_size_mb=config.auto_debugger.logging.max_log_size_mb,
        backup_count=config.auto_debugger.logging.backup_count,
        structured=config.auto_debugger.logging.structured_logging
    )
    
    app = FastAPI(
        title="FACTRADE RAG System API",
        description="Auto-updating RAG system with built-in quality checks and auto-debugging",
        version=config.system.version
    )
    
    if config.api.cors_enabled:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    
    rag_system = None
    
    @app.on_event("startup")
    async def startup_event():
        nonlocal rag_system
        logger.info("starting_api_server")
        rag_system = RAGSystem()
        rag_system.start_auto_update()
        logger.info("api_server_started")
    
    @app.on_event("shutdown")
    async def shutdown_event():
        logger.info("shutting_down_api_server")
        if rag_system:
            rag_system.stop_auto_update()
        logger.info("api_server_stopped")
    
    @app.get("/")
    async def root():
        return {
            "message": "FACTRADE RAG System API",
            "version": config.system.version,
            "status": "running"
        }
    
    @app.post("/query", response_model=QueryResponse)
    async def query(request: QueryRequest):
        try:
            logger.info("api_query_received", question=request.question[:100])
            
            result = rag_system.query(request.question)
            
            return QueryResponse(
                question=result["question"],
                answer=result["answer"],
                sources=result["sources"],
                metrics=result["metrics"],
                quality_checks=result["quality_checks"],
                timestamp=datetime.utcnow().isoformat()
            )
        
        except Exception as e:
            logger.error("query_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/documents/add")
    async def add_documents(request: AddDocumentsRequest, background_tasks: BackgroundTasks):
        try:
            logger.info("api_add_documents_received", count=len(request.file_paths))
            
            background_tasks.add_task(rag_system.add_documents, request.file_paths)
            
            return {
                "message": "Documents are being processed",
                "file_count": len(request.file_paths)
            }
        
        except Exception as e:
            logger.error("add_documents_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.delete("/documents/source/{source:path}")
    async def delete_document(source: str):
        try:
            logger.info("api_delete_document_received", source=source)
            
            rag_system.delete_document_by_source(source)
            
            return {
                "message": "Document deleted",
                "source": source
            }
        
        except Exception as e:
            logger.error("delete_document_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/health", response_model=HealthResponse)
    async def health():
        try:
            health_status = rag_system.get_health_status()
            return HealthResponse(**health_status)
        
        except Exception as e:
            logger.error("health_check_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/statistics", response_model=StatisticsResponse)
    async def statistics():
        try:
            stats = rag_system.get_statistics()
            return StatisticsResponse(**stats)
        
        except Exception as e:
            logger.error("statistics_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/integrity-check")
    async def integrity_check():
        try:
            logger.info("api_integrity_check_received")
            
            results = rag_system.run_integrity_check()
            
            return results
        
        except Exception as e:
            logger.error("integrity_check_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/performance-summary")
    async def performance_summary(operation: Optional[str] = None):
        try:
            summary = rag_system.get_performance_summary(operation)
            return summary
        
        except Exception as e:
            logger.error("performance_summary_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/error-summary")
    async def error_summary(last_n_minutes: int = 60):
        try:
            summary = rag_system.get_error_summary(last_n_minutes)
            return summary
        
        except Exception as e:
            logger.error("error_summary_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.post("/reindex")
    async def reindex(background_tasks: BackgroundTasks):
        try:
            logger.info("api_reindex_received")
            
            background_tasks.add_task(rag_system.force_reindex)
            
            return {
                "message": "Reindexing started"
            }
        
        except Exception as e:
            logger.error("reindex_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/query-patterns")
    async def query_patterns():
        try:
            patterns = rag_system.auto_debugger.get_query_patterns()
            return {"patterns": patterns}
        
        except Exception as e:
            logger.error("query_patterns_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/memory-leak-check")
    async def memory_leak_check():
        try:
            results = rag_system.auto_debugger.detect_memory_leaks()
            return results
        
        except Exception as e:
            logger.error("memory_leak_check_failed", error=str(e))
            raise HTTPException(status_code=500, detail=str(e))
    
    return app


app = create_app()
