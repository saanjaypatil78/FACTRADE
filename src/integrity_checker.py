import hashlib
import numpy as np
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime
from collections import defaultdict
import structlog

logger = structlog.get_logger()


class IntegrityChecker:
    def __init__(self, config):
        self.config = config
        self.integrity_config = config.quality_checks.integrity
        self.issues_found = []
        logger.info("integrity_checker_initialized")

    def check_all(self, vector_store, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        logger.info("starting_integrity_checks")
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "checks_performed": [],
            "issues_found": [],
            "status": "pass",
            "summary": {}
        }

        if self.integrity_config.validate_embeddings:
            embedding_results = self._validate_embeddings(vector_store)
            results["checks_performed"].append("embedding_validation")
            results["summary"]["embedding_validation"] = embedding_results
            if not embedding_results["valid"]:
                results["issues_found"].extend(embedding_results["issues"])
                results["status"] = "fail"

        if self.integrity_config.check_duplicates:
            duplicate_results = self._check_duplicates(documents)
            results["checks_performed"].append("duplicate_detection")
            results["summary"]["duplicate_detection"] = duplicate_results
            if duplicate_results["duplicates_found"]:
                results["issues_found"].extend(duplicate_results["issues"])
                results["status"] = "warning" if results["status"] == "pass" else results["status"]

        if self.integrity_config.verify_metadata:
            metadata_results = self._verify_metadata(documents)
            results["checks_performed"].append("metadata_verification")
            results["summary"]["metadata_verification"] = metadata_results
            if not metadata_results["valid"]:
                results["issues_found"].extend(metadata_results["issues"])
                results["status"] = "fail"

        if self.integrity_config.check_orphaned_documents:
            orphan_results = self._check_orphaned_documents(vector_store, documents)
            results["checks_performed"].append("orphaned_document_check")
            results["summary"]["orphaned_document_check"] = orphan_results
            if orphan_results["orphans_found"]:
                results["issues_found"].extend(orphan_results["issues"])
                results["status"] = "warning" if results["status"] == "pass" else results["status"]

        logger.info(
            "integrity_checks_completed",
            status=results["status"],
            issues_count=len(results["issues_found"])
        )
        
        return results

    def _validate_embeddings(self, vector_store) -> Dict[str, Any]:
        logger.debug("validating_embeddings")
        
        try:
            collection = vector_store._collection
            count = collection.count()
            
            if count == 0:
                return {
                    "valid": True,
                    "total_embeddings": 0,
                    "issues": []
                }

            sample_size = min(100, count)
            results = collection.peek(sample_size)
            
            embeddings = results.get('embeddings', [])
            ids = results.get('ids', [])
            
            issues = []
            expected_dimension = self.config.embeddings.dimension
            
            for idx, (embedding, doc_id) in enumerate(zip(embeddings, ids)):
                if embedding is None:
                    issues.append({
                        "type": "null_embedding",
                        "document_id": doc_id,
                        "severity": "critical"
                    })
                    continue
                
                if len(embedding) != expected_dimension:
                    issues.append({
                        "type": "dimension_mismatch",
                        "document_id": doc_id,
                        "expected": expected_dimension,
                        "actual": len(embedding),
                        "severity": "critical"
                    })
                
                if np.isnan(embedding).any():
                    issues.append({
                        "type": "nan_values",
                        "document_id": doc_id,
                        "severity": "critical"
                    })
                
                if np.isinf(embedding).any():
                    issues.append({
                        "type": "inf_values",
                        "document_id": doc_id,
                        "severity": "critical"
                    })
                
                magnitude = np.linalg.norm(embedding)
                if magnitude < 1e-10:
                    issues.append({
                        "type": "zero_magnitude",
                        "document_id": doc_id,
                        "severity": "warning"
                    })

            return {
                "valid": len([i for i in issues if i["severity"] == "critical"]) == 0,
                "total_embeddings": count,
                "sampled": sample_size,
                "issues": issues
            }

        except Exception as e:
            logger.error("embedding_validation_failed", error=str(e))
            return {
                "valid": False,
                "error": str(e),
                "issues": [{
                    "type": "validation_error",
                    "message": str(e),
                    "severity": "critical"
                }]
            }

    def _check_duplicates(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        logger.debug("checking_duplicates")
        
        content_hashes = defaultdict(list)
        issues = []
        
        for doc in documents:
            content = doc.get('page_content', '') or doc.get('content', '')
            if not content:
                continue
            
            content_hash = hashlib.sha256(content.encode()).hexdigest()
            content_hashes[content_hash].append(doc.get('id', doc.get('metadata', {}).get('id', 'unknown')))
        
        duplicates = {k: v for k, v in content_hashes.items() if len(v) > 1}
        
        for content_hash, doc_ids in duplicates.items():
            issues.append({
                "type": "duplicate_content",
                "document_ids": doc_ids,
                "count": len(doc_ids),
                "severity": "warning"
            })
        
        return {
            "duplicates_found": len(duplicates) > 0,
            "duplicate_count": len(duplicates),
            "total_duplicated_documents": sum(len(v) for v in duplicates.values()),
            "issues": issues
        }

    def _verify_metadata(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        logger.debug("verifying_metadata")
        
        required_fields = ['source', 'created_at']
        issues = []
        
        for idx, doc in enumerate(documents):
            metadata = doc.get('metadata', {})
            
            if not metadata:
                issues.append({
                    "type": "missing_metadata",
                    "document_index": idx,
                    "document_id": doc.get('id', 'unknown'),
                    "severity": "warning"
                })
                continue
            
            for field in required_fields:
                if field not in metadata:
                    issues.append({
                        "type": "missing_metadata_field",
                        "field": field,
                        "document_index": idx,
                        "document_id": doc.get('id', 'unknown'),
                        "severity": "warning"
                    })
            
            if 'source' in metadata:
                source = metadata['source']
                if not isinstance(source, str) or not source.strip():
                    issues.append({
                        "type": "invalid_source",
                        "document_index": idx,
                        "document_id": doc.get('id', 'unknown'),
                        "severity": "warning"
                    })

        return {
            "valid": len([i for i in issues if i["severity"] == "critical"]) == 0,
            "total_documents": len(documents),
            "issues": issues
        }

    def _check_orphaned_documents(self, vector_store, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        logger.debug("checking_orphaned_documents")
        
        try:
            collection = vector_store._collection
            stored_ids = set(collection.get()['ids'])
            
            document_ids = set()
            for doc in documents:
                doc_id = doc.get('id') or doc.get('metadata', {}).get('id')
                if doc_id:
                    document_ids.add(str(doc_id))
            
            orphaned_in_store = stored_ids - document_ids
            orphaned_in_docs = document_ids - stored_ids
            
            issues = []
            
            for orphan_id in orphaned_in_store:
                issues.append({
                    "type": "orphaned_in_vector_store",
                    "document_id": orphan_id,
                    "severity": "warning",
                    "message": "Document exists in vector store but not in document list"
                })
            
            for orphan_id in orphaned_in_docs:
                issues.append({
                    "type": "orphaned_in_document_list",
                    "document_id": orphan_id,
                    "severity": "warning",
                    "message": "Document exists in document list but not in vector store"
                })

            return {
                "orphans_found": len(orphaned_in_store) + len(orphaned_in_docs) > 0,
                "orphaned_in_store_count": len(orphaned_in_store),
                "orphaned_in_docs_count": len(orphaned_in_docs),
                "issues": issues
            }

        except Exception as e:
            logger.error("orphan_check_failed", error=str(e))
            return {
                "orphans_found": False,
                "error": str(e),
                "issues": [{
                    "type": "check_error",
                    "message": str(e),
                    "severity": "warning"
                }]
            }

    def auto_fix_issues(self, results: Dict[str, Any], vector_store, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        logger.info("attempting_auto_fix", issues_count=len(results["issues_found"]))
        
        fixes_applied = []
        
        for issue in results["issues_found"]:
            if issue["type"] == "duplicate_content":
                fix_result = self._fix_duplicates(issue, vector_store)
                fixes_applied.append(fix_result)
            
            elif issue["type"] == "orphaned_in_vector_store":
                fix_result = self._remove_orphaned_from_store(issue, vector_store)
                fixes_applied.append(fix_result)
        
        return {
            "fixes_attempted": len(fixes_applied),
            "fixes_successful": len([f for f in fixes_applied if f.get("success")]),
            "details": fixes_applied
        }

    def _fix_duplicates(self, issue: Dict[str, Any], vector_store) -> Dict[str, Any]:
        try:
            doc_ids = issue["document_ids"]
            ids_to_remove = doc_ids[1:]
            
            vector_store._collection.delete(ids=ids_to_remove)
            
            logger.info("duplicates_removed", count=len(ids_to_remove))
            return {
                "issue_type": "duplicate_content",
                "success": True,
                "removed_ids": ids_to_remove
            }
        except Exception as e:
            logger.error("duplicate_fix_failed", error=str(e))
            return {
                "issue_type": "duplicate_content",
                "success": False,
                "error": str(e)
            }

    def _remove_orphaned_from_store(self, issue: Dict[str, Any], vector_store) -> Dict[str, Any]:
        try:
            doc_id = issue["document_id"]
            vector_store._collection.delete(ids=[doc_id])
            
            logger.info("orphaned_document_removed", document_id=doc_id)
            return {
                "issue_type": "orphaned_in_vector_store",
                "success": True,
                "removed_id": doc_id
            }
        except Exception as e:
            logger.error("orphan_removal_failed", error=str(e))
            return {
                "issue_type": "orphaned_in_vector_store",
                "success": False,
                "error": str(e)
            }
