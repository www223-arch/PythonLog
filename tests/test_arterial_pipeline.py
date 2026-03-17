import os
import sys
import unittest


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SRC_DIR = os.path.join(ROOT_DIR, 'src')
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from analytics.heatmap.pressure_grid_adapter import PressureGridAdapter
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


if __name__ == '__main__':
    unittest.main()
