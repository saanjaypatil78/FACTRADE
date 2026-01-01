import pytest
from src.quality_checker import QualityChecker
from src.config_manager import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def quality_checker(config):
    return QualityChecker(config)


def test_quality_checker_initialization(quality_checker):
    assert quality_checker is not None
    assert quality_checker.config is not None


def test_check_retrieval_quality_fast(quality_checker):
    query = "What is machine learning?"
    retrieved_docs = [
        {
            'page_content': 'Machine learning is a subset of AI',
            'metadata': {'source': 'doc1.txt'},
            'score': 0.9
        },
        {
            'page_content': 'ML algorithms learn from data',
            'metadata': {'source': 'doc2.txt'},
            'score': 0.85
        }
    ]
    retrieval_time_ms = 100
    
    result = quality_checker.check_retrieval_quality(query, retrieved_docs, retrieval_time_ms)
    
    assert result['passed'] is True
    assert result['checks']['retrieval_time']['passed'] is True
    assert result['checks']['similarity_scores']['average'] > 0


def test_check_retrieval_quality_slow(quality_checker):
    query = "Test query"
    retrieved_docs = [
        {'page_content': 'Content', 'metadata': {}, 'score': 0.8}
    ]
    retrieval_time_ms = 1000
    
    result = quality_checker.check_retrieval_quality(query, retrieved_docs, retrieval_time_ms)
    
    assert result['passed'] is False
    assert any(issue['type'] == 'slow_retrieval' for issue in result['issues'])


def test_check_retrieval_quality_no_documents(quality_checker):
    query = "Test query"
    retrieved_docs = []
    retrieval_time_ms = 100
    
    result = quality_checker.check_retrieval_quality(query, retrieved_docs, retrieval_time_ms)
    
    assert result['passed'] is False
    assert any(issue['type'] == 'no_documents_retrieved' for issue in result['issues'])


def test_check_response_length_valid(quality_checker):
    response = "This is a valid response that meets the minimum length requirement."
    
    result = quality_checker._check_response_length(response)
    
    assert result['passed'] is True


def test_check_response_length_too_short(quality_checker):
    response = "Short"
    
    result = quality_checker._check_response_length(response)
    
    assert result['passed'] is False


def test_check_hallucination_grounded(quality_checker):
    response = "Machine learning is a type of artificial intelligence."
    sources = [
        {
            'page_content': 'Machine learning is a type of artificial intelligence that enables computers to learn.',
            'metadata': {}
        }
    ]
    
    result = quality_checker._check_hallucination(response, sources)
    
    assert result['confidence'] > 0.5


def test_check_hallucination_no_sources(quality_checker):
    response = "Some response"
    sources = []
    
    result = quality_checker._check_hallucination(response, sources)
    
    assert result['passed'] is False


def test_verify_sources_valid(quality_checker):
    response = "Test response"
    sources = [
        {'page_content': 'Valid content', 'metadata': {'source': 'test.txt'}}
    ]
    
    result = quality_checker._verify_sources(response, sources)
    
    assert result['passed'] is True


def test_verify_sources_empty_content(quality_checker):
    response = "Test response"
    sources = [
        {'metadata': {'source': 'test.txt'}}
    ]
    
    result = quality_checker._verify_sources(response, sources)
    
    assert result['passed'] is False


def test_check_coherence(quality_checker):
    response = "First, we need to understand the basics. However, there are some exceptions. Therefore, we must be careful."
    
    result = quality_checker._check_coherence(response)
    
    assert 'score' in result
    assert result['passed'] in [True, False]


def test_check_toxicity_clean(quality_checker):
    response = "This is a helpful and respectful response."
    
    result = quality_checker._check_toxicity(response)
    
    assert result['passed'] is True


def test_check_toxicity_toxic(quality_checker):
    response = "This is stupid and terrible."
    
    result = quality_checker._check_toxicity(response)
    
    assert result['passed'] is False


def test_check_performance_within_limits(quality_checker):
    result = quality_checker.check_performance(
        query_time_ms=1000,
        embedding_time_ms=500,
        memory_usage_mb=1024
    )
    
    assert result['passed'] is True


def test_check_performance_exceeds_limits(quality_checker):
    result = quality_checker.check_performance(
        query_time_ms=3000,
        embedding_time_ms=500,
        memory_usage_mb=1024
    )
    
    assert result['passed'] is False
    assert any(issue['type'] == 'slow_query' for issue in result['issues'])


def test_check_response_quality_integration(quality_checker):
    query = "What is AI?"
    response = "Artificial Intelligence is a field of computer science focused on creating intelligent machines."
    sources = [
        {
            'page_content': 'Artificial Intelligence (AI) is a field of computer science.',
            'metadata': {'source': 'ai.txt'}
        }
    ]
    generation_time_ms = 500
    
    result = quality_checker.check_response_quality(query, response, sources, generation_time_ms)
    
    assert 'checks' in result
    assert 'passed' in result
    assert 'length' in result['checks']
