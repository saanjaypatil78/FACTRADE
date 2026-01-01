import pytest
import time
from src.auto_debugger import AutoDebugger, CircuitBreaker
from src.config_manager import Config


@pytest.fixture
def config():
    return Config()


@pytest.fixture
def auto_debugger(config):
    return AutoDebugger(config)


def test_auto_debugger_initialization(auto_debugger):
    assert auto_debugger is not None
    assert auto_debugger.config is not None
    assert auto_debugger.health_status['status'] == 'healthy'


def test_circuit_breaker_closed_state():
    cb = CircuitBreaker(threshold=3, timeout=5)
    
    def successful_function():
        return "success"
    
    result = cb.call(successful_function)
    assert result == "success"
    assert cb.state == "closed"


def test_circuit_breaker_opens_after_failures():
    cb = CircuitBreaker(threshold=3, timeout=5)
    
    def failing_function():
        raise Exception("Test failure")
    
    for _ in range(3):
        try:
            cb.call(failing_function)
        except Exception:
            pass
    
    assert cb.state == "open"


def test_circuit_breaker_rejects_calls_when_open():
    cb = CircuitBreaker(threshold=1, timeout=1)
    
    def failing_function():
        raise Exception("Test failure")
    
    try:
        cb.call(failing_function)
    except Exception:
        pass
    
    with pytest.raises(Exception) as exc_info:
        cb.call(failing_function)
    
    assert "Circuit breaker is OPEN" in str(exc_info.value)


def test_with_retry_success(auto_debugger):
    call_count = [0]
    
    def function_that_works():
        call_count[0] += 1
        return "success"
    
    result = auto_debugger.with_retry(function_that_works)
    
    assert result == "success"
    assert call_count[0] == 1


def test_with_retry_eventual_success(auto_debugger):
    call_count = [0]
    
    def function_that_fails_twice():
        call_count[0] += 1
        if call_count[0] < 3:
            raise Exception("Temporary failure")
        return "success"
    
    result = auto_debugger.with_retry(function_that_fails_twice)
    
    assert result == "success"
    assert call_count[0] == 3


def test_with_retry_max_attempts_exceeded(auto_debugger):
    def always_fails():
        raise Exception("Permanent failure")
    
    with pytest.raises(Exception) as exc_info:
        auto_debugger.with_retry(always_fails)
    
    assert "Permanent failure" in str(exc_info.value)


def test_track_query(auto_debugger):
    auto_debugger.track_query("What is machine learning")
    auto_debugger.track_query("What is machine learning")
    auto_debugger.track_query("What is deep learning")
    
    patterns = auto_debugger.get_query_patterns()
    
    assert "what is machine learning" in patterns
    assert patterns["what is machine learning"] == 2


def test_performance_monitoring_decorator(auto_debugger):
    @auto_debugger.monitor_performance("test_operation")
    def test_function():
        time.sleep(0.01)
        return "result"
    
    result = test_function()
    
    assert result == "result"
    assert "test_operation" in auto_debugger.performance_metrics
    assert len(auto_debugger.performance_metrics["test_operation"]) > 0


def test_error_recording(auto_debugger):
    error = ValueError("Test error")
    auto_debugger._record_error("test_operation", error)
    
    assert len(auto_debugger.error_history) > 0
    assert auto_debugger.error_history[-1]['operation'] == "test_operation"
    assert auto_debugger.error_history[-1]['error_type'] == "ValueError"


def test_health_check(auto_debugger):
    health_status = auto_debugger.health_check()
    
    assert 'status' in health_status
    assert 'last_check' in health_status
    assert 'issues' in health_status
    assert 'metrics' in health_status
    assert health_status['status'] in ['healthy', 'degraded', 'critical']


def test_get_performance_summary_no_data(auto_debugger):
    summary = auto_debugger.get_performance_summary("nonexistent_operation")
    
    assert summary['data_points'] == 0


def test_get_performance_summary_with_data(auto_debugger):
    auto_debugger.performance_metrics["test_op"] = [
        {
            "timestamp": "2024-01-01T00:00:00",
            "execution_time_ms": 100,
            "memory_delta_mb": 10,
            "memory_usage_mb": 100
        },
        {
            "timestamp": "2024-01-01T00:00:01",
            "execution_time_ms": 150,
            "memory_delta_mb": 15,
            "memory_usage_mb": 115
        }
    ]
    
    summary = auto_debugger.get_performance_summary("test_op")
    
    assert summary['data_points'] == 2
    assert 'execution_time' in summary
    assert summary['execution_time']['mean_ms'] == 125.0


def test_get_error_summary(auto_debugger):
    error = Exception("Test error")
    auto_debugger._record_error("operation1", error)
    auto_debugger._record_error("operation2", error)
    
    summary = auto_debugger.get_error_summary(last_n_minutes=60)
    
    assert summary['total_errors'] >= 2


def test_detect_memory_leaks_disabled(auto_debugger):
    auto_debugger.monitoring_config.memory_leak_detection = False
    
    result = auto_debugger.detect_memory_leaks()
    
    assert result['enabled'] is False


def test_reset_metrics(auto_debugger):
    auto_debugger.performance_metrics["test"] = [{"data": "test"}]
    auto_debugger.query_patterns["test"] = 1
    auto_debugger.error_history.append({"error": "test"})
    
    auto_debugger.reset_metrics()
    
    assert len(auto_debugger.performance_metrics) == 0
    assert len(auto_debugger.query_patterns) == 0
    assert len(auto_debugger.error_history) == 0
