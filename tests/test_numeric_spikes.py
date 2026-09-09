import unittest

import numpy as np

from bpx_v2_dataset_pipeline.server.numeric_spikes import repair_isolated_spikes


class NumericSpikesTest(unittest.TestCase):
    def test_repairs_only_isolated_center_spike(self):
        values = np.asarray([[0.0], [0.1], [5.0], [0.2], [0.3]], dtype=np.float32)
        result = repair_isolated_spikes(
            values,
            jump_thresholds=np.asarray([1.0]),
            neighbor_thresholds=np.asarray([0.2]),
        )
        self.assertEqual(result.count, 1)
        np.testing.assert_allclose(result.repaired[:, 0], [0.0, 0.1, 0.15, 0.2, 0.3])

    def test_does_not_flatten_sustained_motion(self):
        values = np.asarray([[0.0], [2.0], [4.0], [6.0]], dtype=np.float32)
        result = repair_isolated_spikes(
            values,
            jump_thresholds=np.asarray([1.0]),
            neighbor_thresholds=np.asarray([0.2]),
        )
        self.assertEqual(result.count, 0)


if __name__ == "__main__":
    unittest.main()
