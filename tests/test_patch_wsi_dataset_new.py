# Copyright (c) MONAI Consortium
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import unittest
from unittest import skipUnless

import numpy as np
from numpy.testing import assert_array_equal
from parameterized import parameterized

from monai.data import PatchWSIDataset
from monai.data.wsi_reader import CuCIMWSIReader, OpenSlideWSIReader
from monai.utils import optional_import
from tests.utils import download_url_or_skip_test, testing_data_config

cucim, has_cucim = optional_import("cucim")
has_cucim = has_cucim and hasattr(cucim, "CuImage")
openslide, has_osl = optional_import("openslide")
imwrite, has_tiff = optional_import("tifffile", name="imwrite")
_, has_codec = optional_import("imagecodecs")
has_tiff = has_tiff and has_codec

FILE_KEY = "wsi_img"
FILE_URL = testing_data_config("images", FILE_KEY, "url")
base_name, extension = os.path.basename(f"{FILE_URL}"), ".tiff"
FILE_PATH = os.path.join(os.path.dirname(__file__), "testing_data", "temp_" + base_name + extension)

TEST_CASE_0 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "label": [1], "level": 0}], "size": (1, 1)},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([1])},
]

TEST_CASE_0_L1 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "label": [1]}], "size": (1, 1), "level": 1},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([1])},
]

TEST_CASE_0_L2 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "label": [1]}], "size": (1, 1), "level": 1},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([1])},
]
TEST_CASE_1 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "size": 1, "label": [1]}]},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([1])},
]

TEST_CASE_2 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "label": [1]}], "size": 1, "level": 0},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([1])},
]

TEST_CASE_3 = [
    {"data": [{"image": FILE_PATH, "location": [0, 0], "label": [[[0, 1], [1, 0]]]}], "size": 1},
    {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([[[0, 1], [1, 0]]])},
]

TEST_CASE_4 = [
    {
        "data": [
            {"image": FILE_PATH, "location": [0, 0], "label": [[[0, 1], [1, 0]]]},
            {"image": FILE_PATH, "location": [0, 0], "label": [[[1, 0], [0, 0]]]},
        ],
        "size": 1,
    },
    [
        {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([[[0, 1], [1, 0]]])},
        {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([[[1, 0], [0, 0]]])},
    ],
]

TEST_CASE_5 = [
    {
        "data": [
            {"image": FILE_PATH, "location": [0, 0], "label": [[[0, 1], [1, 0]]], "size": 1, "level": 1},
            {"image": FILE_PATH, "location": [100, 100], "label": [[[1, 0], [0, 0]]], "size": 1, "level": 1},
        ]
    },
    [
        {"image": np.array([[[239]], [[239]], [[239]]], dtype=np.uint8), "label": np.array([[[0, 1], [1, 0]]])},
        {"image": np.array([[[243]], [[243]], [[243]]], dtype=np.uint8), "label": np.array([[[1, 0], [0, 0]]])},
    ],
]


@skipUnless(has_cucim or has_osl or has_tiff, "Requires cucim, openslide, or tifffile!")
def setUpModule():  # noqa: N802
    hash_type = testing_data_config("images", FILE_KEY, "hash_type")
    hash_val = testing_data_config("images", FILE_KEY, "hash_val")
    download_url_or_skip_test(FILE_URL, FILE_PATH, hash_type=hash_type, hash_val=hash_val)


class PatchWSIDatasetTests:
    class Tests(unittest.TestCase):
        backend = None

        @parameterized.expand([TEST_CASE_0, TEST_CASE_0_L1, TEST_CASE_0_L2, TEST_CASE_1, TEST_CASE_2, TEST_CASE_3])
        def test_read_patches_str(self, input_parameters, expected):
            dataset = PatchWSIDataset(reader=self.backend, **input_parameters)
            sample = dataset[0]
            self.assertTupleEqual(sample["label"].shape, expected["label"].shape)
            self.assertTupleEqual(sample["image"].shape, expected["image"].shape)
            self.assertIsNone(assert_array_equal(sample["label"], expected["label"]))
            self.assertIsNone(assert_array_equal(sample["image"], expected["image"]))

        @parameterized.expand([TEST_CASE_0, TEST_CASE_0_L1, TEST_CASE_0_L2, TEST_CASE_1, TEST_CASE_2, TEST_CASE_3])
        def test_read_patches_class(self, input_parameters, expected):
            if self.backend == "openslide":
                reader = OpenSlideWSIReader
            elif self.backend == "cucim":
                reader = CuCIMWSIReader
            else:
                raise ValueError("Unsupported backend: {self.backend}")
            dataset = PatchWSIDataset(reader=reader, **input_parameters)
            sample = dataset[0]
            self.assertTupleEqual(sample["label"].shape, expected["label"].shape)
            self.assertTupleEqual(sample["image"].shape, expected["image"].shape)
            self.assertIsNone(assert_array_equal(sample["label"], expected["label"]))
            self.assertIsNone(assert_array_equal(sample["image"], expected["image"]))

        @parameterized.expand([TEST_CASE_0, TEST_CASE_0_L1, TEST_CASE_0_L2, TEST_CASE_1, TEST_CASE_2, TEST_CASE_3])
        def test_read_patches_object(self, input_parameters, expected):
            if self.backend == "openslide":
                reader = OpenSlideWSIReader(level=input_parameters.get("level", 0))
            elif self.backend == "cucim":
                reader = CuCIMWSIReader(level=input_parameters.get("level", 0))
            else:
                raise ValueError("Unsupported backend: {self.backend}")
            dataset = PatchWSIDataset(reader=reader, **input_parameters)
            sample = dataset[0]
            self.assertTupleEqual(sample["label"].shape, expected["label"].shape)
            self.assertTupleEqual(sample["image"].shape, expected["image"].shape)
            self.assertIsNone(assert_array_equal(sample["label"], expected["label"]))
            self.assertIsNone(assert_array_equal(sample["image"], expected["image"]))

        @parameterized.expand([TEST_CASE_4, TEST_CASE_5])
        def test_read_patches_str_multi(self, input_parameters, expected):
            dataset = PatchWSIDataset(reader=self.backend, **input_parameters)
            for i in range(len(dataset)):
                self.assertTupleEqual(dataset[i]["label"].shape, expected[i]["label"].shape)
                self.assertTupleEqual(dataset[i]["image"].shape, expected[i]["image"].shape)
                self.assertIsNone(assert_array_equal(dataset[i]["label"], expected[i]["label"]))
                self.assertIsNone(assert_array_equal(dataset[i]["image"], expected[i]["image"]))


@skipUnless(has_cucim, "Requires cucim")
class TestPatchWSIDatasetCuCIM(PatchWSIDatasetTests.Tests):
    @classmethod
    def setUpClass(cls):
        cls.backend = "cucim"


@skipUnless(has_osl, "Requires cucim")
class TestPatchWSIDatasetOpenSlide(PatchWSIDatasetTests.Tests):
    @classmethod
    def setUpClass(cls):
        cls.backend = "openslide"


if __name__ == "__main__":
    unittest.main()
