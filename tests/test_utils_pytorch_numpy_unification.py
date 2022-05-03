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

import unittest

import numpy as np
from parameterized import parameterized

from monai.transforms.utils_pytorch_numpy_unification import mode, percentile
from monai.utils import set_determinism
from tests.utils import TEST_NDARRAYS, assert_allclose

TEST_MODE = []
for p in TEST_NDARRAYS:
    TEST_MODE.append([p(np.array([1, 2, 3, 4, 4, 5])), p(4), False])
    TEST_MODE.append([p(np.array([3.1, 4.1, 4.1, 5.1])), p(4.1), False])
    TEST_MODE.append([p(np.array([3.1, 4.1, 4.1, 5.1])), p(4), True])


class TestPytorchNumpyUnification(unittest.TestCase):
    def setUp(self) -> None:
        set_determinism(0)

    def test_percentile(self):
        for size in (1, 100):
            q = np.random.randint(0, 100, size=size)
            results = []
            for p in TEST_NDARRAYS:
                arr = p(np.arange(100 * 101).reshape(1, 100, 101).astype(np.float32))
                results.append(percentile(arr, q))
                assert_allclose(results[0], results[-1], type_test=False, atol=1e-4)

    def test_fails(self):
        for p in TEST_NDARRAYS:
            for q in (-1, 101):
                arr = p(np.arange(100 * 101).reshape(1, 100, 101).astype(np.float32))
                with self.assertRaises(ValueError):
                    percentile(arr, q)

    def test_dim(self):
        q = np.random.randint(0, 100, size=50)
        results = []
        for p in TEST_NDARRAYS:
            arr = p(np.arange(6).reshape(1, 2, 3).astype(np.float32))
            results.append(percentile(arr, q, dim=1))
            assert_allclose(results[0], results[-1], type_test=False, atol=1e-4)

    @parameterized.expand(TEST_MODE)
    def test_mode(self, array, expected, to_long):
        res = mode(array, to_long=to_long)
        assert_allclose(res, expected)


if __name__ == "__main__":
    unittest.main()
