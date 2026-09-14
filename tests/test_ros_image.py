from types import SimpleNamespace

import numpy as np
import pytest

from bpx_v2_dataset_pipeline.collector.ros_image import RosImageError, image_message_to_rgb


def message(encoding: str, data: bytes, *, width: int = 2, height: int = 1, step: int = 6):
    return SimpleNamespace(encoding=encoding, data=data, width=width, height=height, step=step)


def test_bgr8_is_converted_to_rgb_and_row_padding_is_ignored() -> None:
    msg = message("bgr8", bytes([3, 2, 1, 6, 5, 4, 99, 99]), step=8)
    result = image_message_to_rgb(msg, expected_width=2, expected_height=1)
    np.testing.assert_array_equal(result, [[[1, 2, 3], [4, 5, 6]]])


def test_invalid_shape_and_short_data_are_rejected() -> None:
    with pytest.raises(RosImageError, match="expected 640x480"):
        image_message_to_rgb(message("rgb8", bytes(6)))
    with pytest.raises(RosImageError, match="expected at least"):
        image_message_to_rgb(message("rgb8", bytes(5)), expected_width=2, expected_height=1)
