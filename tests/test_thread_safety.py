"""
Tests for thread safety and parallel processing correctness.

Validates:
- MemoryBoundedLRUCache under concurrent access
- calculate_statistics_parallel() produces identical results to sequential
- Double-analysis prevention in _ensure_sample_analyzed()
"""

import pytest
import threading
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch, call

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from flowkit_gui.utils.cache import MemoryBoundedLRUCache
from flowkit_gui.models.statistics_model import StatisticsModel, MFIMetric, GateStatistics
from flowkit_gui.models.workspace_model import Sample, DataSource


# =============================================================================
# Helpers
# =============================================================================

def create_mock_sample(sample_id, name, event_count=10000):
    """Create a mock sample."""
    return Sample(
        sample_id=sample_id,
        name=name,
        fcs_path=None,
        group="",
        keywords={},
        event_count=event_count
    )


def create_mock_workspace_for_stats(samples, channels):
    """Create a mock workspace suitable for statistics testing.

    Returns predictable numeric data so sequential and parallel results
    can be compared exactly.
    """
    mock_workspace = Mock()
    mock_workspace.samples = samples

    def get_gate_statistics(sample_id, gate_id):
        return {'count': 100, 'percent_parent': 50.0, 'percent_total': 10.0}

    def has_fcs_data(sample_id):
        return True

    def get_gated_events(sample_id, gate_id, channels_list=None, data_source=None):
        # Return deterministic data based on sample_id hash
        rng = np.random.RandomState(hash(sample_id + gate_id) % 2**31)
        n_events = 100
        data = {}
        for ch in (channels_list or channels):
            data[ch] = rng.exponential(scale=500, size=n_events).astype(np.float64)
        return pd.DataFrame(data)

    mock_workspace.get_gate_statistics = Mock(side_effect=get_gate_statistics)
    mock_workspace.has_fcs_data = Mock(side_effect=has_fcs_data)
    mock_workspace.get_gated_events = Mock(side_effect=get_gated_events)

    return mock_workspace


# =============================================================================
# Cache Thread Safety Tests
# =============================================================================

class TestCacheThreadSafety:
    """Verify MemoryBoundedLRUCache is safe under concurrent access."""

    def test_concurrent_put_get(self):
        """4 threads doing random put/get — no exceptions, no corruption."""
        cache = MemoryBoundedLRUCache(max_bytes=10 * 1024**2)  # 10MB
        errors = []

        def worker(thread_id):
            try:
                for i in range(100):
                    key = f"thread{thread_id}_item{i}"
                    arr = np.random.randn(100).astype(np.float64)
                    cache.put(key, arr)
                    result = cache.get(key)
                    # May be None if evicted by another thread, but must not crash
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Cache errors: {errors}"

    def test_concurrent_put_eviction(self):
        """Concurrent puts that trigger eviction — no corruption."""
        cache = MemoryBoundedLRUCache(max_bytes=1024 * 100)  # 100KB — forces evictions
        errors = []

        def worker(thread_id):
            try:
                for i in range(50):
                    key = f"t{thread_id}_i{i}"
                    arr = np.random.randn(500).astype(np.float64)  # ~4KB each
                    cache.put(key, arr)
            except Exception as e:
                errors.append((thread_id, e))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Eviction errors: {errors}"
        # Cache should be consistent: current_bytes should match actual contents
        actual_bytes = sum(v.nbytes for v in cache._cache.values())
        assert cache._current_bytes == actual_bytes

    def test_concurrent_clear(self):
        """Concurrent clear + put — no exceptions."""
        cache = MemoryBoundedLRUCache(max_bytes=10 * 1024**2)
        errors = []

        def putter(thread_id):
            try:
                for i in range(50):
                    cache.put(f"t{thread_id}_{i}", np.zeros(10))
            except Exception as e:
                errors.append(("putter", thread_id, e))

        def clearer():
            try:
                for _ in range(10):
                    cache.clear()
            except Exception as e:
                errors.append(("clearer", e))

        threads = [threading.Thread(target=putter, args=(i,)) for i in range(3)]
        threads.append(threading.Thread(target=clearer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Clear errors: {errors}"


# =============================================================================
# Parallel Statistics Correctness Tests
# =============================================================================

class TestParallelStatisticsCorrectness:
    """Verify parallel statistics produce identical results to sequential."""

    def test_parallel_matches_sequential(self):
        """Both methods must produce the same GateStatistics for each sample/gate."""
        samples = [create_mock_sample(f"S{i}", f"Sample {i}") for i in range(8)]
        channels = ['Ki67', 'CD3', 'CD8']
        gate_ids = ['Gate_A', 'Gate_B']
        metrics = [MFIMetric.MEAN, MFIMetric.MEDIAN]

        # Run sequential
        ws_seq = create_mock_workspace_for_stats(samples, channels)
        model_seq = StatisticsModel(ws_seq)
        model_seq.calculate_statistics(
            gate_ids=gate_ids,
            channels=channels,
            metrics=metrics
        )

        # Run parallel
        ws_par = create_mock_workspace_for_stats(samples, channels)
        model_par = StatisticsModel(ws_par)
        model_par.calculate_statistics_parallel(
            gate_ids=gate_ids,
            channels=channels,
            metrics=metrics,
            max_workers=4
        )

        # Compare results
        seq_stats = model_seq._statistics
        par_stats = model_par._statistics

        assert set(seq_stats.keys()) == set(par_stats.keys()), \
            "Different sample IDs in results"

        for sample_id in seq_stats:
            assert set(seq_stats[sample_id].keys()) == set(par_stats[sample_id].keys()), \
                f"Different gate IDs for sample {sample_id}"

            for gate_id in seq_stats[sample_id]:
                seq_gate = seq_stats[sample_id][gate_id]
                par_gate = par_stats[sample_id][gate_id]

                assert seq_gate.event_count == par_gate.event_count, \
                    f"Event count mismatch for {sample_id}/{gate_id}"
                assert seq_gate.percent_of_parent == par_gate.percent_of_parent, \
                    f"Percent of parent mismatch for {sample_id}/{gate_id}"

                # Compare MFI values
                for channel in channels:
                    seq_mfi = seq_gate.mfi_values.get(channel, {})
                    par_mfi = par_gate.mfi_values.get(channel, {})
                    assert set(seq_mfi.keys()) == set(par_mfi.keys()), \
                        f"Different MFI keys for {sample_id}/{gate_id}/{channel}"
                    for metric_key in seq_mfi:
                        seq_val = seq_mfi[metric_key]
                        par_val = par_mfi[metric_key]
                        if np.isnan(seq_val) and np.isnan(par_val):
                            continue  # Both NaN is fine
                        assert abs(seq_val - par_val) < 1e-10, \
                            f"MFI mismatch for {sample_id}/{gate_id}/{channel}/{metric_key}: " \
                            f"{seq_val} vs {par_val}"

    def test_parallel_handles_no_fcs_data(self):
        """Samples without FCS data should produce warnings, not crashes."""
        samples = [create_mock_sample(f"S{i}", f"Sample {i}") for i in range(3)]
        channels = ['Ki67']
        gate_ids = ['Gate_A']

        mock_workspace = create_mock_workspace_for_stats(samples, channels)
        # Second sample has no FCS data
        mock_workspace.has_fcs_data = Mock(side_effect=lambda sid: sid != 'S1')

        model = StatisticsModel(mock_workspace)
        model.calculate_statistics_parallel(
            gate_ids=gate_ids,
            channels=channels,
            metrics=[MFIMetric.MEAN],
            max_workers=2
        )

        warnings = model.get_warnings()
        assert any('Sample 1' in w for w in warnings)

    def test_parallel_with_single_sample(self):
        """Edge case: parallelism with only 1 sample should still work."""
        samples = [create_mock_sample('S0', 'Only Sample')]
        channels = ['Ki67']
        gate_ids = ['Gate_A']

        mock_workspace = create_mock_workspace_for_stats(samples, channels)
        model = StatisticsModel(mock_workspace)
        model.calculate_statistics_parallel(
            gate_ids=gate_ids,
            channels=channels,
            metrics=[MFIMetric.MEAN],
            max_workers=4
        )

        assert 'S0' in model._statistics
        assert 'Gate_A' in model._statistics['S0']


# =============================================================================
# Double-Analysis Prevention Tests
# =============================================================================

class TestDoubleAnalysisPrevention:
    """Verify that _ensure_sample_analyzed prevents redundant FlowKit calls."""

    def test_analyzed_sample_skipped(self):
        """Already-analyzed samples should not trigger re-analysis."""
        from flowkit_gui.models.workspace_model import WorkspaceModel

        model = WorkspaceModel()
        model._workspace = Mock()
        model._analyzed_samples.add('S1')

        model._ensure_sample_analyzed('S1')

        # FlowKit should NOT have been called
        model._workspace.analyze_samples.assert_not_called()

    def test_failed_sample_skipped(self):
        """Previously failed samples should not be retried."""
        from flowkit_gui.models.workspace_model import WorkspaceModel

        model = WorkspaceModel()
        model._workspace = Mock()
        with model._failed_samples_lock:
            model._failed_samples['S1'] = 'Previous error'

        model._ensure_sample_analyzed('S1')

        model._workspace.analyze_samples.assert_not_called()

    def test_concurrent_analysis_calls_once(self):
        """Multiple threads analyzing the same sample: FlowKit called exactly once."""
        from flowkit_gui.models.workspace_model import WorkspaceModel

        model = WorkspaceModel()
        mock_ws = Mock()
        call_count = [0]
        call_lock = threading.Lock()

        def mock_analyze(**kwargs):
            with call_lock:
                call_count[0] += 1
            # Simulate some work
            import time
            time.sleep(0.01)

        mock_ws.analyze_samples = Mock(side_effect=mock_analyze)
        model._workspace = mock_ws

        barrier = threading.Barrier(4)
        errors = []

        def worker():
            try:
                barrier.wait(timeout=5)  # Sync all threads to start together
                model._ensure_sample_analyzed('S1')
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Worker errors: {errors}"
        assert call_count[0] == 1, \
            f"analyze_samples called {call_count[0]} times, expected 1"
        assert 'S1' in model._analyzed_samples
