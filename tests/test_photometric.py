import unittest

import numpy as np

from bpx_v2_dataset_pipeline.training.photometric import PhotometricConfig, augment_views


class PhotometricTest(unittest.TestCase):
    def test_same_parameters_are_shared_across_views(self):
        image = np.full((8, 8, 3), 100, dtype=np.uint8)
        output = augment_views(
            {"left": image, "right": image.copy()},
            config=PhotometricConfig(probability=1),
            rng=np.random.default_rng(7),
        )
        np.testing.assert_array_equal(output["left"], output["right"])

    def test_disabled_augmentation_returns_independent_copy(self):
        image = np.full((4, 4, 3), 100, dtype=np.uint8)
        output = augment_views(
            {"left": image},
            config=PhotometricConfig(probability=0),
            rng=np.random.default_rng(1),
        )
        np.testing.assert_array_equal(output["left"], image)
        self.assertIsNot(output["left"], image)


if __name__ == "__main__":
    unittest.main()
