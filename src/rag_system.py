import time
import os
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
import psutil

from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    TextLoader,
    UnstructuredMarkdownLoader
)
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings, ChatOpenAI
from langchain.chains import RetrievalQA
from langchain.prompts import PromptTemplate

import structlog

from .config_manager import get_config
from .integrity_checker import IntegrityChecker
from .quality_checker import QualityChecker
from .auto_debugger import AutoDebugger
from .auto_updater import AutoUpdater

logger = structlog.get_logger()


class RAGSystem:
    def __init__(self, config_path: Optional[str] = None):
        self.config = get_config()
        
        self.embeddings = None
        self.vector_store = None
        self.llm = None
        self.text_splitter = None
        self.retriever = None
        self.qa_chain = None
        
        self.integrity_checker = IntegrityChecker(self.config)
        self.quality_checker = QualityChecker(self.config)
        self.auto_debugger = AutoDebugger(self.config)
        self.auto_updater = AutoUpdater(self.config, rag_system=self)
        
        self.documents = []
        
        self._initialize_components()
        
        logger.info("rag_system_initialized", config_environment=self.config.system.environment)

    def _initialize_components(self):
        logger.info("initializing_rag_components")
        
        self._setup_embeddings()
        self._setup_vector_store()
        self._setup_llm()
        self._setup_text_splitter()
        self._setup_retriever()
        self._setup_qa_chain()

    def _setup_embeddings(self):
        logger.info("setting_up_embeddings", provider=self.config.embeddings.provider)
        
        if self.config.embeddings.provider == "openai":
            self.embeddings = OpenAIEmbeddings(
                model=self.config.embeddings.model,
                chunk_size=self.config.embeddings.batch_size
            )
        else:
            raise ValueError(f"Unsupported embeddings provider: {self.config.embeddings.provider}")

    def _setup_vector_store(self):
        logger.info("setting_up_vector_store", type=self.config.vector_store.type)
        
        persist_dir = Path(self.config.vector_store.persist_directory)
        persist_dir.mkdir(parents=True, exist_ok=True)
        
        if self.config.vector_store.type == "chromadb":
            self.vector_store = Chroma(
                collection_name=self.config.vector_store.collection_name,
                embedding_function=self.embeddings,
                persist_directory=str(persist_dir)
            )
        else:
            raise ValueError(f"Unsupported vector store type: {self.config.vector_store.type}")

    def _setup_llm(self):
        logger.info("setting_up_llm", provider=self.config.llm.provider)
        
        if self.config.llm.provider == "openai":
            self.llm = ChatOpenAI(
                model=self.config.llm.model,
                temperature=self.config.llm.temperature,
                max_tokens=self.config.llm.max_tokens
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.config.llm.provider}")

    def _setup_text_splitter(self):
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config.document_processing.chunk_size,
            chunk_overlap=self.config.document_processing.chunk_overlap,
            separators=self.config.document_processing.separators
        )

    def _setup_retriever(self):
        search_kwargs = {
            "k": self.config.retrieval.top_k
        }
        
        self.retriever = self.vector_store.as_retriever(
            search_kwargs=search_kwargs
        )

    def _setup_qa_chain(self):
        prompt_template = """Use the following pieces of context to answer the question at the end. 
If you don't know the answer, just say that you don't know, don't try to make up an answer.
Always cite the sources you used to answer the question.

Context:
{context}

Question: {question}

Answer: """
        
        PROMPT = PromptTemplate(
            template=prompt_template,
            input_variables=["context", "question"]
        )
        
        self.qa_chain = RetrievalQA.from_chain_type(
            llm=self.llm,
            chain_type="stuff",
            retriever=self.retriever,
            return_source_documents=True,
            chain_type_kwargs={"prompt": PROMPT}
        )

    @AutoDebugger.monitor_performance
    def add_documents(self, file_paths: List[str]):
        logger.info("adding_documents", count=len(file_paths))
        
        def _add_docs():
            all_documents = []
            
            for file_path in file_paths:
                try:
                    documents = self._load_document(file_path)
                    all_documents.extend(documents)
                    logger.debug("document_loaded", path=file_path, chunks=len(documents))
                except Exception as e:
                    logger.error("failed_to_load_document", path=file_path, error=str(e))
            
            if all_documents:
                splits = self.text_splitter.split_documents(all_documents)
                
                for i, split in enumerate(splits):
                    split.metadata['chunk_id'] = i
                    split.metadata['created_at'] = datetime.utcnow().isoformat()
                
                self.vector_store.add_documents(splits)
                self.documents.extend(splits)
                
                logger.info("documents_added", total_chunks=len(splits))
        
        self.auto_debugger.with_retry(_add_docs)

    def _load_document(self, file_path: str):
        file_path_obj = Path(file_path)
        suffix = file_path_obj.suffix.lower()
        
        if suffix == '.pdf':
            loader = PyPDFLoader(file_path)
        elif suffix in ['.docx', '.doc']:
            loader = Docx2txtLoader(file_path)
        elif suffix == '.md':
            loader = UnstructuredMarkdownLoader(file_path)
        elif suffix == '.txt':
            loader = TextLoader(file_path)
        else:
            raise ValueError(f"Unsupported file format: {suffix}")
        
        documents = loader.load()
        
        for doc in documents:
            doc.metadata['source'] = file_path
        
        return documents

    def delete_document_by_source(self, source: str):
        logger.info("deleting_document_by_source", source=source)
        
        def _delete():
            try:
                collection = self.vector_store._collection
                results = collection.get()
                
                ids_to_delete = []
                for i, metadata in enumerate(results['metadatas']):
                    if metadata.get('source') == source:
                        ids_to_delete.append(results['ids'][i])
                
                if ids_to_delete:
                    collection.delete(ids=ids_to_delete)
                    logger.info("document_deleted", source=source, chunks_removed=len(ids_to_delete))
                
                self.documents = [doc for doc in self.documents if doc.metadata.get('source') != source]
            
            except Exception as e:
                logger.error("failed_to_delete_document", source=source, error=str(e))
                raise
        
        self.auto_debugger.with_retry(_delete)

    def query(self, question: str) -> Dict[str, Any]:
        logger.info("processing_query", question=question[:100])
        
        self.auto_debugger.track_query(question)
        
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss / 1024 / 1024
        
        retrieval_start = time.time()
        retrieved_docs = self.retriever.get_relevant_documents(question)
        retrieval_time_ms = (time.time() - retrieval_start) * 1000
        
        retrieval_quality = self.quality_checker.check_retrieval_quality(
            query=question,
            retrieved_docs=[{
                'page_content': doc.page_content,
                'metadata': doc.metadata,
                'score': 0.8
            } for doc in retrieved_docs],
            retrieval_time_ms=retrieval_time_ms
        )
        
        generation_start = time.time()
        
        def _generate_response():
            return self.qa_chain({"query": question})
        
        result = self.auto_debugger.with_retry(_generate_response)
        generation_time_ms = (time.time() - generation_start) * 1000
        
        response = result['result']
        source_documents = result['source_documents']
        
        response_quality = self.quality_checker.check_response_quality(
            query=question,
            response=response,
            sources=[{
                'page_content': doc.page_content,
                'metadata': doc.metadata
            } for doc in source_documents],
            generation_time_ms=generation_time_ms
        )
        
        end_time = time.time()
        end_memory = psutil.Process().memory_info().rss / 1024 / 1024
        
        total_time_ms = (end_time - start_time) * 1000
        
        performance_check = self.quality_checker.check_performance(
            query_time_ms=total_time_ms,
            embedding_time_ms=retrieval_time_ms,
            memory_usage_mb=end_memory
        )
        
        return {
            "question": question,
            "answer": response,
            "sources": [
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata
                }
                for doc in source_documents
            ],
            "metrics": {
                "retrieval_time_ms": retrieval_time_ms,
                "generation_time_ms": generation_time_ms,
                "total_time_ms": total_time_ms,
                "memory_delta_mb": end_memory - start_memory
            },
            "quality_checks": {
                "retrieval": retrieval_quality,
                "response": response_quality,
                "performance": performance_check
            }
        }

    def run_integrity_check(self) -> Dict[str, Any]:
        logger.info("running_integrity_check")
        
        results = self.integrity_checker.check_all(self.vector_store, self.documents)
        
        if results["status"] == "fail" and self.config.auto_debugger.self_healing.enabled:
            logger.info("attempting_auto_fix_for_integrity_issues")
            fix_results = self.integrity_checker.auto_fix_issues(results, self.vector_store, self.documents)
            results["auto_fix"] = fix_results
        
        return results

    def get_health_status(self) -> Dict[str, Any]:
        return self.auto_debugger.health_check()

    def get_performance_summary(self, operation: Optional[str] = None) -> Dict[str, Any]:
        return self.auto_debugger.get_performance_summary(operation)

    def get_error_summary(self, last_n_minutes: int = 60) -> Dict[str, Any]:
        return self.auto_debugger.get_error_summary(last_n_minutes)

    def start_auto_update(self):
        self.auto_updater.start()

    def stop_auto_update(self):
        self.auto_updater.stop()

    def force_reindex(self):
        self.auto_updater.full_reindex()

    def clear(self):
        logger.warning("clearing_vector_store")
        
        collection = self.vector_store._collection
        collection.delete(where={})
        
        self.documents = []
        logger.info("vector_store_cleared")

    def get_statistics(self) -> Dict[str, Any]:
        try:
            collection = self.vector_store._collection
            doc_count = collection.count()
        except:
            doc_count = 0
        
        return {
            "total_documents": doc_count,
            "total_chunks": len(self.documents),
            "vector_store_type": self.config.vector_store.type,
            "embedding_model": self.config.embeddings.model,
            "llm_model": self.config.llm.model,
            "auto_update_enabled": self.config.auto_update.enabled,
            "quality_checks_enabled": self.config.quality_checks.enabled
        }
