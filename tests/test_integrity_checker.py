import pytest
import numpy as np
from unittest.mock import Mock, MagicMock
from src.integrity_checker import IntegrityChecker
from src.config_manager import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def integrity_checker(config):
    return IntegrityChecker(config)


def test_integrity_checker_initialization(integrity_checker):
    assert integrity_checker is not None
    assert integrity_checker.config is not None


def test_validate_embeddings_with_valid_data(integrity_checker):
    mock_vector_store = Mock()
    mock_collection = Mock()
    
    mock_collection.count.return_value = 10
    mock_collection.peek.return_value = {
        'embeddings': [np.random.rand(1536).tolist() for _ in range(10)],
        'ids': [f"doc_{i}" for i in range(10)]
    }
    
    mock_vector_store._collection = mock_collection
    
    result = integrity_checker._validate_embeddings(mock_vector_store)
    
    assert result['valid'] is True
    assert result['total_embeddings'] == 10


def test_validate_embeddings_with_nan_values(integrity_checker):
    mock_vector_store = Mock()
    mock_collection = Mock()
    
    invalid_embedding = np.random.rand(1536).tolist()
    invalid_embedding[0] = float('nan')
    
    mock_collection.count.return_value = 1
    mock_collection.peek.return_value = {
        'embeddings': [invalid_embedding],
        'ids': ['doc_1']
    }
    
    mock_vector_store._collection = mock_collection
    
    result = integrity_checker._validate_embeddings(mock_vector_store)
    
    assert result['valid'] is False
    assert any(issue['type'] == 'nan_values' for issue in result['issues'])


def test_check_duplicates(integrity_checker):
    documents = [
        {'page_content': 'This is a test document', 'id': 'doc_1'},
        {'page_content': 'This is a test document', 'id': 'doc_2'},
        {'page_content': 'Another document', 'id': 'doc_3'}
    ]
    
    result = integrity_checker._check_duplicates(documents)
    
    assert result['duplicates_found'] is True
    assert result['duplicate_count'] == 1


def test_verify_metadata_missing_fields(integrity_checker):
    documents = [
        {'page_content': 'Test', 'metadata': {'source': 'test.txt'}},
        {'page_content': 'Test 2', 'metadata': {}},
    ]
    
    result = integrity_checker._verify_metadata(documents)
    
    assert len(result['issues']) > 0
    assert any(issue['type'] == 'missing_metadata_field' for issue in result['issues'])


def test_check_all_integration(integrity_checker):
    mock_vector_store = Mock()
    mock_collection = Mock()
    
    mock_collection.count.return_value = 2
    mock_collection.peek.return_value = {
        'embeddings': [np.random.rand(1536).tolist() for _ in range(2)],
        'ids': ['doc_1', 'doc_2']
    }
    mock_collection.get.return_value = {
        'ids': ['doc_1', 'doc_2']
    }
    
    mock_vector_store._collection = mock_collection
    
    documents = [
        {
            'page_content': 'Test document',
            'id': 'doc_1',
            'metadata': {'source': 'test.txt', 'created_at': '2024-01-01'}
        }
    ]
    
    result = integrity_checker.check_all(mock_vector_store, documents)
    
    assert 'status' in result
    assert 'checks_performed' in result
    assert 'issues_found' in result


def test_auto_fix_duplicates(integrity_checker):
    mock_vector_store = Mock()
    mock_collection = Mock()
    mock_vector_store._collection = mock_collection
    
    issue = {
        'type': 'duplicate_content',
        'document_ids': ['doc_1', 'doc_2', 'doc_3']
    }
    
    fix_result = integrity_checker._fix_duplicates(issue, mock_vector_store)
    
    assert fix_result['success'] is True
    assert len(fix_result['removed_ids']) == 2
    mock_collection.delete.assert_called_once()
