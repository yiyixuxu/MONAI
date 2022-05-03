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
import tempfile
import unittest
from unittest import skipUnless

import numpy as np
from parameterized import parameterized

from monai.bundle import ConfigParser, ReferenceResolver
from monai.data import DataLoader, Dataset
from monai.transforms import Compose, LoadImaged, RandTorchVisiond
from monai.utils import min_version, optional_import

_, has_tv = optional_import("torchvision", "0.8.0", min_version)

# test the resolved and parsed instances
TEST_CASE_1 = [
    {
        "transform": {
            "_target_": "Compose",
            "transforms": [
                {"_target_": "LoadImaged", "keys": "image"},
                # test relative id in `keys`
                {"_target_": "RandTorchVisiond", "keys": "@##0#keys", "name": "ColorJitter", "brightness": 0.25},
            ],
        },
        "dataset": {"_target_": "Dataset", "data": [1, 2], "transform": "@transform"},
        "dataloader": {
            "_target_": "DataLoader",
            # test relative id in `dataset`
            "dataset": "@##dataset",
            "batch_size": 2,
            "collate_fn": "$monai.data.list_data_collate",
        },
    },
    ["transform", "transform#transforms#0", "transform#transforms#1", "dataset", "dataloader"],
    [Compose, LoadImaged, RandTorchVisiond, Dataset, DataLoader],
]


class TestClass:
    @staticmethod
    def compute(a, b, func=lambda x, y: x + y):
        return func(a, b)

    @classmethod
    def cls_compute(cls, a, b, func=lambda x, y: x + y):
        return cls.compute(a, b, func)

    def __call__(self, a, b):
        return self.compute(a, b)


TEST_CASE_2 = [
    {
        "basic_func": "$lambda x, y: x + y",
        "static_func": "$TestClass.compute",
        "cls_func": "$TestClass.cls_compute",
        "lambda_static_func": "$lambda x, y: TestClass.compute(x, y)",
        "lambda_cls_func": "$lambda x, y: TestClass.cls_compute(x, y)",
        "compute": {"_target_": "tests.test_config_parser.TestClass.compute", "func": "@basic_func"},
        "cls_compute": {"_target_": "tests.test_config_parser.TestClass.cls_compute", "func": "@basic_func"},
        "call_compute": {"_target_": "tests.test_config_parser.TestClass"},
        "error_func": "$TestClass.__call__",
        "<test>": "$lambda x, y: x + y",
    }
]


TEST_CASE_3 = [
    {
        "A": 1,
        "B": "@A",
        "C": "@#A",
        "D": {"key": "@##A", "value1": 2, "value2": "%#value1", "value3": [3, 4, "@#1", "$100 + @#0 + @##value1"]},
    }
]

TEST_CASE_4 = [{"A": 1, "B": "@A", "C": "@D", "E": "$'test' + '@F'"}]


class TestConfigParser(unittest.TestCase):
    def test_config_content(self):
        test_config = {"preprocessing": [{"_target_": "LoadImage"}], "dataset": {"_target_": "Dataset"}}
        parser = ConfigParser(config=test_config)
        # test `get`, `set`, `__getitem__`, `__setitem__`
        self.assertEqual(str(parser.get()), str(test_config))
        parser.set(config=test_config)
        self.assertListEqual(parser["preprocessing"], test_config["preprocessing"])
        parser["dataset"] = {"_target_": "CacheDataset"}
        self.assertEqual(parser["dataset"]["_target_"], "CacheDataset")
        # test nested ids
        parser["dataset#_target_"] = "Dataset"
        self.assertEqual(parser["dataset#_target_"], "Dataset")
        # test int id
        parser.set(["test1", "test2", "test3"])
        parser[1] = "test4"
        self.assertEqual(parser[1], "test4")

    @parameterized.expand([TEST_CASE_1])
    @skipUnless(has_tv, "Requires torchvision >= 0.8.0.")
    def test_parse(self, config, expected_ids, output_types):
        parser = ConfigParser(config=config, globals={"monai": "monai"})
        # test lazy instantiation with original config content
        parser["transform"]["transforms"][0]["keys"] = "label1"
        trans = parser.get_parsed_content(id="transform#transforms#0")
        self.assertEqual(trans.keys[0], "label1")
        # test re-use the parsed content or not with the `lazy` option
        self.assertEqual(trans, parser.get_parsed_content(id="transform#transforms#0"))
        self.assertEqual(trans, parser.get_parsed_content(id="transform#transforms#0", lazy=True))
        self.assertNotEqual(trans, parser.get_parsed_content(id="transform#transforms#0", lazy=False))
        # test nested id
        parser["transform#transforms#0#keys"] = "label2"
        self.assertEqual(parser.get_parsed_content(id="transform#transforms#0").keys[0], "label2")
        for id, cls in zip(expected_ids, output_types):
            self.assertTrue(isinstance(parser.get_parsed_content(id), cls))
        # test root content
        root = parser.get_parsed_content(id="")
        for v, cls in zip(root.values(), [Compose, Dataset, DataLoader]):
            self.assertTrue(isinstance(v, cls))

    @parameterized.expand([TEST_CASE_2])
    def test_function(self, config):
        parser = ConfigParser(config=config, globals={"TestClass": TestClass})
        for id in config:
            func = parser.get_parsed_content(id=id)
            self.assertTrue(id in parser.ref_resolver.resolved_content)
            if id == "error_func":
                with self.assertRaises(TypeError):
                    func(1, 2)
                continue
            self.assertEqual(func(1, 2), 3)

    @parameterized.expand([TEST_CASE_3])
    def test_relative_id(self, config):
        parser = ConfigParser(config=config)
        for id in config:
            item = parser.get_parsed_content(id=id)
            if isinstance(item, int):
                self.assertEqual(item, 1)
            if isinstance(item, dict):
                self.assertEqual(str(item), str({"key": 1, "value1": 2, "value2": 2, "value3": [3, 4, 4, 105]}))

    def test_macro_replace(self):
        with tempfile.TemporaryDirectory() as tempdir:
            another_file = os.path.join(tempdir, "another.json")
            ConfigParser.export_config_file(config={"E": 4}, filepath=another_file)
            # test macro with id, relative id, and macro in another file
            config = {"A": {"B": 1, "C": 2}, "D": [3, "%A#B", "%#0", f"%{another_file}#E"]}
            parser = ConfigParser(config=config)
            parser.resolve_macro_and_relative_ids()
            self.assertEqual(str(parser.get()), str({"A": {"B": 1, "C": 2}, "D": [3, 1, 3, 4]}))

    @parameterized.expand([TEST_CASE_4])
    def test_allow_missing_reference(self, config):
        default = ReferenceResolver.allow_missing_reference
        ReferenceResolver.allow_missing_reference = True
        parser = ConfigParser(config=config)

        for id in config:
            item = parser.get_parsed_content(id=id)
            if id in ("A", "B"):
                self.assertEqual(item, 1)
            elif id == "C":
                self.assertEqual(item, "@D")
            elif id == "E":
                self.assertEqual(item, "test@F")

        # restore the default value
        ReferenceResolver.allow_missing_reference = default
        with self.assertRaises(ValueError):
            parser.parse()
            parser.get_parsed_content(id="E")

    def test_list_expressions(self):
        config = {
            "transform": {
                "_target_": "Compose",
                "transforms": [{"_target_": "RandScaleIntensity", "factors": 0.5, "prob": 1.0}],
            },
            "training": ["$monai.utils.set_determinism(seed=123)", "$@transform(np.asarray([1, 2]))"],
        }
        parser = ConfigParser(config=config)
        parser.get_parsed_content("training", lazy=True, instantiate=True, eval_expr=True)
        np.testing.assert_allclose(parser.get_parsed_content("training#1", lazy=True), [0.7942, 1.5885], atol=1e-4)


if __name__ == "__main__":
    unittest.main()
