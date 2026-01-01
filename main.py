import os
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.config_manager import get_config
from src.logger import setup_logging
from src.rag_system import RAGSystem
import structlog

logger = structlog.get_logger()


def main():
    parser = argparse.ArgumentParser(description="FACTRADE RAG System")
    parser.add_argument(
        "--mode",
        choices=["api", "cli", "test"],
        default="api",
        help="Run mode: api (REST API server), cli (interactive CLI), or test (run tests)"
    )
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to configuration file"
    )
    parser.add_argument(
        "--add-documents",
        nargs="+",
        help="Add documents to the system (CLI mode)"
    )
    parser.add_argument(
        "--query",
        help="Query the system (CLI mode)"
    )
    parser.add_argument(
        "--integrity-check",
        action="store_true",
        help="Run integrity check (CLI mode)"
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Force reindex all documents (CLI mode)"
    )
    
    args = parser.parse_args()
    
    if args.config:
        os.environ['CONFIG_PATH'] = args.config
    
    config = get_config()
    
    setup_logging(
        log_level=config.auto_debugger.logging.level,
        log_directory=config.auto_debugger.logging.log_directory,
        max_log_size_mb=config.auto_debugger.logging.max_log_size_mb,
        backup_count=config.auto_debugger.logging.backup_count,
        structured=config.auto_debugger.logging.structured_logging
    )
    
    logger.info("starting_factrade_rag_system", mode=args.mode, version=config.system.version)
    
    if args.mode == "api":
        run_api_server(config)
    elif args.mode == "cli":
        run_cli(args, config)
    elif args.mode == "test":
        run_tests()


def run_api_server(config):
    import uvicorn
    from src.api import app
    
    logger.info("starting_api_server", host=config.api.host, port=config.api.port)
    
    uvicorn.run(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level=config.auto_debugger.logging.level.lower()
    )


def run_cli(args, config):
    logger.info("starting_cli_mode")
    
    rag_system = RAGSystem()
    
    try:
        if args.add_documents:
            logger.info("adding_documents", count=len(args.add_documents))
            rag_system.add_documents(args.add_documents)
            print(f"✓ Added {len(args.add_documents)} documents")
        
        if args.query:
            logger.info("processing_query", query=args.query[:100])
            result = rag_system.query(args.query)
            
            print("\n" + "="*80)
            print("QUESTION:")
            print(result["question"])
            print("\n" + "-"*80)
            print("ANSWER:")
            print(result["answer"])
            print("\n" + "-"*80)
            print("SOURCES:")
            for i, source in enumerate(result["sources"], 1):
                print(f"\n{i}. {source['metadata'].get('source', 'Unknown')}")
                print(f"   {source['content'][:200]}...")
            print("\n" + "-"*80)
            print("METRICS:")
            for key, value in result["metrics"].items():
                print(f"  {key}: {value}")
            print("\n" + "-"*80)
            print("QUALITY CHECKS:")
            for check_type, check_result in result["quality_checks"].items():
                status = "✓ PASS" if check_result.get("passed") else "✗ FAIL"
                print(f"  {check_type}: {status}")
            print("="*80 + "\n")
        
        if args.integrity_check:
            logger.info("running_integrity_check")
            results = rag_system.run_integrity_check()
            
            print("\n" + "="*80)
            print("INTEGRITY CHECK RESULTS")
            print("="*80)
            print(f"Status: {results['status'].upper()}")
            print(f"Checks performed: {', '.join(results['checks_performed'])}")
            print(f"Issues found: {len(results['issues_found'])}")
            
            if results['issues_found']:
                print("\nISSUES:")
                for issue in results['issues_found']:
                    print(f"  - [{issue.get('severity', 'unknown')}] {issue.get('type', 'unknown')}")
            print("="*80 + "\n")
        
        if args.reindex:
            logger.info("forcing_reindex")
            rag_system.start_auto_update()
            rag_system.force_reindex()
            print("✓ Reindexing completed")
            rag_system.stop_auto_update()
        
        if not any([args.add_documents, args.query, args.integrity_check, args.reindex]):
            print("FACTRADE RAG System - Interactive CLI")
            print("="*80)
            
            stats = rag_system.get_statistics()
            print(f"Documents: {stats['total_documents']}")
            print(f"Chunks: {stats['total_chunks']}")
            print(f"Embedding Model: {stats['embedding_model']}")
            print(f"LLM Model: {stats['llm_model']}")
            print("="*80)
            
            rag_system.start_auto_update()
            
            try:
                while True:
                    query = input("\nEnter your question (or 'quit' to exit): ").strip()
                    
                    if query.lower() in ['quit', 'exit', 'q']:
                        break
                    
                    if not query:
                        continue
                    
                    result = rag_system.query(query)
                    
                    print("\n" + "-"*80)
                    print("ANSWER:")
                    print(result["answer"])
                    print("-"*80)
                    print(f"Time: {result['metrics']['total_time_ms']:.2f}ms")
                    
                    quality_status = "✓" if all(
                        check.get("passed", True)
                        for check in result["quality_checks"].values()
                    ) else "✗"
                    print(f"Quality: {quality_status}")
            
            except KeyboardInterrupt:
                print("\n\nExiting...")
            
            finally:
                rag_system.stop_auto_update()
    
    except Exception as e:
        logger.error("cli_error", error=str(e))
        print(f"\n✗ Error: {e}")
        sys.exit(1)


def run_tests():
    import pytest
    logger.info("running_tests")
    sys.exit(pytest.main(["-v", "tests/"]))


if __name__ == "__main__":
    main()
