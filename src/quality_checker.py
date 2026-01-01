import time
import re
from typing import Dict, List, Any, Optional
from datetime import datetime
import numpy as np
import structlog

logger = structlog.get_logger()


class QualityChecker:
    def __init__(self, config):
        self.config = config
        self.quality_config = config.quality_checks
        self.retrieval_config = self.quality_config.retrieval
        self.response_config = self.quality_config.response
        self.performance_config = self.quality_config.performance
        logger.info("quality_checker_initialized")

    def check_retrieval_quality(
        self,
        query: str,
        retrieved_docs: List[Dict[str, Any]],
        retrieval_time_ms: float
    ) -> Dict[str, Any]:
        logger.debug("checking_retrieval_quality", query=query[:50])
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "checks": {},
            "passed": True,
            "issues": []
        }

        if retrieval_time_ms > self.retrieval_config.max_retrieval_time_ms:
            results["passed"] = False
            results["issues"].append({
                "type": "slow_retrieval",
                "retrieval_time_ms": retrieval_time_ms,
                "threshold_ms": self.retrieval_config.max_retrieval_time_ms,
                "severity": "warning"
            })
        
        results["checks"]["retrieval_time"] = {
            "passed": retrieval_time_ms <= self.retrieval_config.max_retrieval_time_ms,
            "value": retrieval_time_ms,
            "threshold": self.retrieval_config.max_retrieval_time_ms
        }

        if not retrieved_docs:
            results["passed"] = False
            results["issues"].append({
                "type": "no_documents_retrieved",
                "severity": "critical"
            })
            results["checks"]["documents_retrieved"] = {
                "passed": False,
                "count": 0
            }
            return results

        similarities = []
        for doc in retrieved_docs:
            score = doc.get('score') or doc.get('similarity', 0)
            similarities.append(score)
        
        avg_similarity = np.mean(similarities) if similarities else 0
        min_similarity = min(similarities) if similarities else 0
        
        similarity_threshold = self.retrieval_config.min_similarity_score
        
        if min_similarity < similarity_threshold:
            results["passed"] = False
            results["issues"].append({
                "type": "low_similarity_score",
                "min_similarity": min_similarity,
                "threshold": similarity_threshold,
                "severity": "warning"
            })
        
        results["checks"]["similarity_scores"] = {
            "passed": min_similarity >= similarity_threshold,
            "average": avg_similarity,
            "minimum": min_similarity,
            "maximum": max(similarities) if similarities else 0,
            "threshold": similarity_threshold
        }

        relevance_check = self._check_relevance(query, retrieved_docs)
        results["checks"]["relevance"] = relevance_check
        
        if not relevance_check["passed"]:
            results["passed"] = False
            results["issues"].append({
                "type": "low_relevance",
                "relevance_score": relevance_check["score"],
                "threshold": self.retrieval_config.relevance_threshold,
                "severity": "warning"
            })

        return results

    def check_response_quality(
        self,
        query: str,
        response: str,
        sources: List[Dict[str, Any]],
        generation_time_ms: float
    ) -> Dict[str, Any]:
        logger.debug("checking_response_quality", query=query[:50])
        
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "query": query,
            "checks": {},
            "passed": True,
            "issues": []
        }

        length_check = self._check_response_length(response)
        results["checks"]["length"] = length_check
        if not length_check["passed"]:
            results["passed"] = False
            results["issues"].append({
                "type": "invalid_length",
                "length": len(response),
                "min": self.response_config.min_response_length,
                "max": self.response_config.max_response_length,
                "severity": "warning"
            })

        if self.response_config.check_hallucination:
            hallucination_check = self._check_hallucination(response, sources)
            results["checks"]["hallucination"] = hallucination_check
            if not hallucination_check["passed"]:
                results["passed"] = False
                results["issues"].append({
                    "type": "potential_hallucination",
                    "confidence": hallucination_check["confidence"],
                    "severity": "critical"
                })

        if self.response_config.verify_sources:
            source_check = self._verify_sources(response, sources)
            results["checks"]["source_verification"] = source_check
            if not source_check["passed"]:
                results["passed"] = False
                results["issues"].append({
                    "type": "source_mismatch",
                    "details": source_check.get("details"),
                    "severity": "warning"
                })

        if self.response_config.check_coherence:
            coherence_check = self._check_coherence(response)
            results["checks"]["coherence"] = coherence_check
            if not coherence_check["passed"]:
                results["passed"] = False
                results["issues"].append({
                    "type": "low_coherence",
                    "score": coherence_check["score"],
                    "severity": "warning"
                })

        if self.response_config.toxicity_check:
            toxicity_check = self._check_toxicity(response)
            results["checks"]["toxicity"] = toxicity_check
            if not toxicity_check["passed"]:
                results["passed"] = False
                results["issues"].append({
                    "type": "toxic_content_detected",
                    "severity": "critical"
                })

        return results

    def _check_relevance(self, query: str, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        query_terms = set(query.lower().split())
        
        relevance_scores = []
        for doc in documents:
            content = doc.get('page_content', '') or doc.get('content', '')
            doc_terms = set(content.lower().split())
            
            if len(query_terms) == 0:
                overlap = 0
            else:
                overlap = len(query_terms.intersection(doc_terms)) / len(query_terms)
            relevance_scores.append(overlap)
        
        avg_relevance = np.mean(relevance_scores) if relevance_scores else 0
        
        return {
            "passed": avg_relevance >= self.retrieval_config.relevance_threshold,
            "score": avg_relevance,
            "threshold": self.retrieval_config.relevance_threshold
        }

    def _check_response_length(self, response: str) -> Dict[str, Any]:
        length = len(response)
        min_length = self.response_config.min_response_length
        max_length = self.response_config.max_response_length
        
        return {
            "passed": min_length <= length <= max_length,
            "length": length,
            "min": min_length,
            "max": max_length
        }

    def _check_hallucination(self, response: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not sources:
            return {
                "passed": False,
                "confidence": 0.0,
                "reason": "no_sources_provided"
            }
        
        response_lower = response.lower()
        
        source_contents = []
        for source in sources:
            content = source.get('page_content', '') or source.get('content', '')
            source_contents.append(content.lower())
        
        combined_sources = ' '.join(source_contents)
        
        response_sentences = re.split(r'[.!?]+', response_lower)
        response_sentences = [s.strip() for s in response_sentences if s.strip()]
        
        if not response_sentences:
            return {
                "passed": True,
                "confidence": 1.0,
                "reason": "empty_response"
            }
        
        grounded_count = 0
        for sentence in response_sentences:
            sentence_terms = set(sentence.split())
            if len(sentence_terms) < 3:
                grounded_count += 1
                continue
            
            found_in_source = False
            for source_content in source_contents:
                source_terms = set(source_content.split())
                overlap = len(sentence_terms.intersection(source_terms))
                
                if overlap >= len(sentence_terms) * 0.5:
                    found_in_source = True
                    break
            
            if found_in_source:
                grounded_count += 1
        
        grounding_ratio = grounded_count / len(response_sentences)
        
        hallucination_threshold = 0.6
        
        return {
            "passed": grounding_ratio >= hallucination_threshold,
            "confidence": grounding_ratio,
            "grounded_sentences": grounded_count,
            "total_sentences": len(response_sentences),
            "threshold": hallucination_threshold
        }

    def _verify_sources(self, response: str, sources: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not sources:
            return {
                "passed": False,
                "details": "No sources provided"
            }
        
        for source in sources:
            if not source.get('page_content') and not source.get('content'):
                return {
                    "passed": False,
                    "details": "Source with empty content found"
                }
        
        return {
            "passed": True,
            "source_count": len(sources)
        }

    def _check_coherence(self, response: str) -> Dict[str, Any]:
        sentences = re.split(r'[.!?]+', response)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) < 2:
            return {
                "passed": True,
                "score": 1.0,
                "reason": "too_short_to_evaluate"
            }
        
        coherence_indicators = [
            r'\b(however|therefore|thus|consequently|moreover|furthermore|additionally)\b',
            r'\b(first|second|third|finally|lastly)\b',
            r'\b(in addition|as a result|for example|for instance)\b',
            r'\b(this|that|these|those)\b',
        ]
        
        coherence_score = 0
        for sentence in sentences[1:]:
            sentence_lower = sentence.lower()
            for pattern in coherence_indicators:
                if re.search(pattern, sentence_lower):
                    coherence_score += 1
                    break
        
        max_possible_score = len(sentences) - 1
        normalized_score = coherence_score / max_possible_score if max_possible_score > 0 else 0
        
        coherence_threshold = 0.3
        
        return {
            "passed": normalized_score >= coherence_threshold or len(sentences) <= 3,
            "score": normalized_score,
            "threshold": coherence_threshold
        }

    def _check_toxicity(self, response: str) -> Dict[str, Any]:
        toxic_patterns = [
            r'\b(hate|stupid|idiot|dumb|kill|die|worst)\b',
            r'\b(sucks|terrible|awful|horrible|disgusting)\b',
        ]
        
        response_lower = response.lower()
        
        for pattern in toxic_patterns:
            if re.search(pattern, response_lower):
                return {
                    "passed": False,
                    "detected_pattern": pattern
                }
        
        return {
            "passed": True
        }

    def check_performance(
        self,
        query_time_ms: float,
        embedding_time_ms: float,
        memory_usage_mb: float
    ) -> Dict[str, Any]:
        results = {
            "timestamp": datetime.utcnow().isoformat(),
            "checks": {},
            "passed": True,
            "issues": []
        }

        if query_time_ms > self.performance_config.max_query_time_ms:
            results["passed"] = False
            results["issues"].append({
                "type": "slow_query",
                "query_time_ms": query_time_ms,
                "threshold_ms": self.performance_config.max_query_time_ms,
                "severity": "warning"
            })
        
        results["checks"]["query_time"] = {
            "passed": query_time_ms <= self.performance_config.max_query_time_ms,
            "value": query_time_ms,
            "threshold": self.performance_config.max_query_time_ms
        }

        if embedding_time_ms > self.performance_config.max_embedding_time_ms:
            results["passed"] = False
            results["issues"].append({
                "type": "slow_embedding",
                "embedding_time_ms": embedding_time_ms,
                "threshold_ms": self.performance_config.max_embedding_time_ms,
                "severity": "warning"
            })
        
        results["checks"]["embedding_time"] = {
            "passed": embedding_time_ms <= self.performance_config.max_embedding_time_ms,
            "value": embedding_time_ms,
            "threshold": self.performance_config.max_embedding_time_ms
        }

        if memory_usage_mb > self.performance_config.max_memory_usage_mb:
            results["passed"] = False
            results["issues"].append({
                "type": "high_memory_usage",
                "memory_usage_mb": memory_usage_mb,
                "threshold_mb": self.performance_config.max_memory_usage_mb,
                "severity": "critical"
            })
        
        results["checks"]["memory_usage"] = {
            "passed": memory_usage_mb <= self.performance_config.max_memory_usage_mb,
            "value": memory_usage_mb,
            "threshold": self.performance_config.max_memory_usage_mb
        }

        return results
