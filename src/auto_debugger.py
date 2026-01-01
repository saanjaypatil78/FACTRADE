import time
import psutil
import traceback
from typing import Dict, Any, Optional, Callable, List
from datetime import datetime, timedelta
from collections import deque, defaultdict
from functools import wraps
import structlog

logger = structlog.get_logger()


class CircuitBreaker:
    def __init__(self, threshold: int, timeout: int):
        self.threshold = threshold
        self.timeout = timeout
        self.failures = 0
        self.last_failure_time = None
        self.state = "closed"

    def call(self, func: Callable, *args, **kwargs):
        if self.state == "open":
            if datetime.now() - self.last_failure_time > timedelta(seconds=self.timeout):
                logger.info("circuit_breaker_half_open", func=func.__name__)
                self.state = "half-open"
            else:
                raise Exception(f"Circuit breaker is OPEN for {func.__name__}")

        try:
            result = func(*args, **kwargs)
            
            if self.state == "half-open":
                logger.info("circuit_breaker_closed", func=func.__name__)
                self.state = "closed"
                self.failures = 0
            
            return result

        except Exception as e:
            self.failures += 1
            self.last_failure_time = datetime.now()
            
            if self.failures >= self.threshold:
                logger.error(
                    "circuit_breaker_open",
                    func=func.__name__,
                    failures=self.failures,
                    threshold=self.threshold
                )
                self.state = "open"
            
            raise


class AutoDebugger:
    def __init__(self, config):
        self.config = config
        self.debugger_config = config.auto_debugger
        self.error_config = self.debugger_config.error_handling
        self.monitoring_config = self.debugger_config.monitoring
        self.self_healing_config = self.debugger_config.self_healing
        
        self.circuit_breakers = {}
        self.error_history = deque(maxlen=1000)
        self.performance_metrics = defaultdict(list)
        self.query_patterns = defaultdict(int)
        
        self.health_status = {
            "status": "healthy",
            "last_check": datetime.utcnow().isoformat(),
            "issues": []
        }
        
        logger.info("auto_debugger_initialized")

    def with_retry(self, func: Callable, *args, **kwargs):
        max_attempts = self.error_config.max_retry_attempts
        backoff_factor = self.error_config.retry_backoff_factor
        
        for attempt in range(max_attempts):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if attempt == max_attempts - 1:
                    logger.error(
                        "max_retries_exceeded",
                        func=func.__name__,
                        attempts=max_attempts,
                        error=str(e)
                    )
                    self._record_error(func.__name__, e)
                    raise
                
                wait_time = backoff_factor ** attempt
                logger.warning(
                    "retry_attempt",
                    func=func.__name__,
                    attempt=attempt + 1,
                    max_attempts=max_attempts,
                    wait_time=wait_time,
                    error=str(e)
                )
                time.sleep(wait_time)

    def with_circuit_breaker(self, func: Callable, *args, **kwargs):
        func_name = func.__name__
        
        if func_name not in self.circuit_breakers:
            self.circuit_breakers[func_name] = CircuitBreaker(
                threshold=self.error_config.circuit_breaker_threshold,
                timeout=self.error_config.circuit_breaker_timeout_seconds
            )
        
        return self.circuit_breakers[func_name].call(func, *args, **kwargs)

    def monitor_performance(self, operation: str):
        def decorator(func: Callable):
            @wraps(func)
            def wrapper(*args, **kwargs):
                start_time = time.time()
                start_memory = psutil.Process().memory_info().rss / 1024 / 1024
                
                try:
                    result = func(*args, **kwargs)
                    
                    end_time = time.time()
                    end_memory = psutil.Process().memory_info().rss / 1024 / 1024
                    
                    execution_time_ms = (end_time - start_time) * 1000
                    memory_delta_mb = end_memory - start_memory
                    
                    self.performance_metrics[operation].append({
                        "timestamp": datetime.utcnow().isoformat(),
                        "execution_time_ms": execution_time_ms,
                        "memory_delta_mb": memory_delta_mb,
                        "memory_usage_mb": end_memory
                    })
                    
                    if len(self.performance_metrics[operation]) > 1000:
                        self.performance_metrics[operation] = self.performance_metrics[operation][-1000:]
                    
                    if self.monitoring_config.performance_profiling:
                        logger.debug(
                            "performance_metric",
                            operation=operation,
                            execution_time_ms=round(execution_time_ms, 2),
                            memory_delta_mb=round(memory_delta_mb, 2)
                        )
                    
                    return result
                
                except Exception as e:
                    self._record_error(operation, e)
                    raise
            
            return wrapper
        return decorator

    def track_query(self, query: str):
        if self.monitoring_config.track_query_patterns:
            normalized_query = ' '.join(query.lower().split()[:5])
            self.query_patterns[normalized_query] += 1

    def _record_error(self, operation: str, error: Exception):
        error_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "operation": operation,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "traceback": traceback.format_exc()
        }
        
        self.error_history.append(error_record)
        
        logger.error(
            "error_recorded",
            operation=operation,
            error_type=error_record["error_type"],
            error_message=error_record["error_message"]
        )
        
        if self.self_healing_config.enabled:
            self._attempt_self_heal(error_record)

    def _attempt_self_heal(self, error_record: Dict[str, Any]):
        error_type = error_record["error_type"]
        operation = error_record["operation"]
        
        logger.info("attempting_self_heal", error_type=error_type, operation=operation)
        
        if error_type == "MemoryError":
            self._handle_memory_error()
        
        elif error_type in ["ConnectionError", "TimeoutError"]:
            self._handle_connection_error()
        
        elif "cache" in operation.lower():
            if self.self_healing_config.cache_invalidation:
                self._invalidate_cache()

    def _handle_memory_error(self):
        logger.warning("handling_memory_error", action="clearing_caches")
        
        import gc
        gc.collect()
        
        if hasattr(self, 'performance_metrics'):
            for key in list(self.performance_metrics.keys()):
                self.performance_metrics[key] = self.performance_metrics[key][-100:]
        
        logger.info("memory_cleanup_completed")

    def _handle_connection_error(self):
        logger.warning("handling_connection_error", action="waiting_for_retry")
        time.sleep(5)

    def _invalidate_cache(self):
        logger.info("invalidating_cache")

    def health_check(self) -> Dict[str, Any]:
        logger.debug("performing_health_check")
        
        issues = []
        
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > 90:
            issues.append({
                "type": "high_cpu_usage",
                "value": cpu_percent,
                "severity": "warning"
            })
        
        memory = psutil.virtual_memory()
        if memory.percent > 90:
            issues.append({
                "type": "high_memory_usage",
                "value": memory.percent,
                "severity": "critical"
            })
        
        recent_errors = [e for e in self.error_history if self._is_recent(e["timestamp"], minutes=5)]
        if len(recent_errors) > 10:
            issues.append({
                "type": "high_error_rate",
                "count": len(recent_errors),
                "severity": "critical"
            })
        
        disk = psutil.disk_usage('/')
        if disk.percent > 90:
            issues.append({
                "type": "low_disk_space",
                "value": disk.percent,
                "severity": "warning"
            })

        status = "healthy"
        if any(i["severity"] == "critical" for i in issues):
            status = "critical"
        elif any(i["severity"] == "warning" for i in issues):
            status = "degraded"
        
        self.health_status = {
            "status": status,
            "last_check": datetime.utcnow().isoformat(),
            "issues": issues,
            "metrics": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory.percent,
                "disk_percent": disk.percent,
                "error_count_5min": len(recent_errors)
            }
        }
        
        logger.info("health_check_completed", status=status, issues_count=len(issues))
        
        return self.health_status

    def _is_recent(self, timestamp: str, minutes: int) -> bool:
        dt = datetime.fromisoformat(timestamp)
        return datetime.utcnow() - dt < timedelta(minutes=minutes)

    def get_performance_summary(self, operation: Optional[str] = None) -> Dict[str, Any]:
        if operation:
            metrics = self.performance_metrics.get(operation, [])
        else:
            metrics = []
            for op_metrics in self.performance_metrics.values():
                metrics.extend(op_metrics)
        
        if not metrics:
            return {
                "operation": operation,
                "data_points": 0
            }
        
        exec_times = [m["execution_time_ms"] for m in metrics]
        memory_deltas = [m["memory_delta_mb"] for m in metrics]
        
        import numpy as np
        
        return {
            "operation": operation or "all",
            "data_points": len(metrics),
            "execution_time": {
                "mean_ms": float(np.mean(exec_times)),
                "median_ms": float(np.median(exec_times)),
                "p95_ms": float(np.percentile(exec_times, 95)),
                "p99_ms": float(np.percentile(exec_times, 99)),
                "min_ms": float(np.min(exec_times)),
                "max_ms": float(np.max(exec_times))
            },
            "memory": {
                "mean_delta_mb": float(np.mean(memory_deltas)),
                "max_delta_mb": float(np.max(memory_deltas)),
                "min_delta_mb": float(np.min(memory_deltas))
            }
        }

    def get_error_summary(self, last_n_minutes: int = 60) -> Dict[str, Any]:
        cutoff_time = datetime.utcnow() - timedelta(minutes=last_n_minutes)
        
        recent_errors = [
            e for e in self.error_history
            if datetime.fromisoformat(e["timestamp"]) > cutoff_time
        ]
        
        error_types = defaultdict(int)
        operations = defaultdict(int)
        
        for error in recent_errors:
            error_types[error["error_type"]] += 1
            operations[error["operation"]] += 1
        
        return {
            "time_window_minutes": last_n_minutes,
            "total_errors": len(recent_errors),
            "error_types": dict(error_types),
            "operations": dict(operations),
            "recent_errors": recent_errors[-10:]
        }

    def get_query_patterns(self) -> Dict[str, int]:
        sorted_patterns = sorted(
            self.query_patterns.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return dict(sorted_patterns[:20])

    def detect_memory_leaks(self) -> Dict[str, Any]:
        if not self.monitoring_config.memory_leak_detection:
            return {"enabled": False}
        
        logger.debug("checking_for_memory_leaks")
        
        memory_metrics = []
        for operation, metrics in self.performance_metrics.items():
            if len(metrics) >= 10:
                recent_memory = [m["memory_usage_mb"] for m in metrics[-10:]]
                older_memory = [m["memory_usage_mb"] for m in metrics[-20:-10]] if len(metrics) >= 20 else []
                
                if older_memory:
                    import numpy as np
                    recent_avg = np.mean(recent_memory)
                    older_avg = np.mean(older_memory)
                    growth_rate = (recent_avg - older_avg) / older_avg if older_avg > 0 else 0
                    
                    if growth_rate > 0.2:
                        memory_metrics.append({
                            "operation": operation,
                            "growth_rate": growth_rate,
                            "recent_avg_mb": recent_avg,
                            "older_avg_mb": older_avg
                        })
        
        potential_leaks = [m for m in memory_metrics if m["growth_rate"] > 0.3]
        
        return {
            "enabled": True,
            "potential_leaks_detected": len(potential_leaks) > 0,
            "leak_candidates": potential_leaks
        }

    def reset_metrics(self):
        logger.info("resetting_metrics")
        self.performance_metrics.clear()
        self.query_patterns.clear()
        self.error_history.clear()
