import os
import sys
import unittest

import pandas as pd


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC_DIR = os.path.join(ROOT_DIR, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from analytics.heatmap.pressure_grid_adapter import PressureGridAdapter
from analytics.ml.model_runner import ModelRunner
from analytics.pipeline import ArterialHealthPipeline


class ArterialPipelineTests(unittest.TestCase):
    def test_pressure_grid_adapter_build_matrix(self):
        adapter = PressureGridAdapter(grid_width=2, grid_height=2)
        channels = {
            'p_0_0': 1.0,
            'p_0_1': 2.0,
            'p_1_0': 3.0,
            'p_1_1': 4.0,
        }
        matrix = adapter.build_matrix(channels)

        self.assertIsNotNone(matrix)
        self.assertEqual(matrix.shape, (2, 2))
        self.assertAlmostEqual(float(matrix[1, 1]), 4.0)

    def test_pipeline_disabled_returns_none(self):
        pipeline = ArterialHealthPipeline(enabled=False, grid_width=2, grid_height=2)
        frame = {
            'timestamp': 1000.0,
            'channels': {'p_0_0': 1.0, 'p_0_1': 2.0, 'p_1_0': 3.0, 'p_1_1': 4.0},
            'meta': {'format_error': False, 'protocol': 'text'},
        }

        result = pipeline.submit_frame(frame)
        self.assertIsNone(result)

    def test_pipeline_generates_result(self):
        pipeline = ArterialHealthPipeline(enabled=True, grid_width=2, grid_height=2)

        result = None
        for i in range(20):
            base = 10.0 + (i % 5)
            frame = {
                'timestamp': 1000.0 + i * 50.0,
                'channels': {
                    'p_0_0': base,
                    'p_0_1': base + 1.0,
                    'p_1_0': base + 2.0,
                    'p_1_1': base + 3.0,
                },
                'meta': {'format_error': False, 'protocol': 'text'},
            }
            result = pipeline.submit_frame(frame)

        self.assertIsNotNone(result)
        self.assertIn('metrics', result)
        self.assertIn('prediction', result)
        self.assertIn('bpm', result['metrics'])

    def test_pipeline_ignores_format_error(self):
        pipeline = ArterialHealthPipeline(enabled=True, grid_width=2, grid_height=2)
        frame = {
            'timestamp': 1000.0,
            'channels': {'p_0_0': 1.0, 'p_0_1': 2.0, 'p_1_0': 3.0, 'p_1_1': 4.0},
            'meta': {'format_error': True, 'protocol': 'text'},
        }
        result = pipeline.submit_frame(frame)
        self.assertIsNone(result)

    def test_model_runner_status_reports_invalid_path(self):
        runner = ModelRunner(model_path='not_exists_model.joblib')
        status = runner.get_status()
        self.assertEqual(status.get('mode'), 'rule')
        self.assertFalse(bool(status.get('has_model')))
        self.assertTrue('不存在' in str(status.get('load_error', '')))

    def test_model_runner_respects_rule_preference(self):
        runner = ModelRunner(model_path='not_exists_model.joblib', model_preference='rule')
        status = runner.get_status()
        self.assertEqual(status.get('mode'), 'rule')
        self.assertEqual(status.get('requested_model'), 'rule')
        self.assertEqual(status.get('detected_model'), 'rule')

    def test_model_runner_builds_dataframe_input_with_feature_names(self):
        runner = ModelRunner(model_path='', feature_order=['b', 'a'])
        model_input = runner._build_model_input({'a': 1.0, 'b': 2.0})

        self.assertIsInstance(model_input, pd.DataFrame)
        self.assertEqual(list(model_input.columns), ['b', 'a'])
        self.assertAlmostEqual(float(model_input.iloc[0]['b']), 2.0)
        self.assertAlmostEqual(float(model_input.iloc[0]['a']), 1.0)


if __name__ == '__main__':
    unittest.main()
