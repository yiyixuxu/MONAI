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

from abc import abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from monai.config import DtypeLike, PathLike
from monai.data.image_reader import ImageReader, _stack_images
from monai.data.utils import is_supported_format
from monai.transforms.utility.array import AsChannelFirst
from monai.utils import ensure_tuple, optional_import, require_pkg

CuImage, _ = optional_import("cucim", name="CuImage")
OpenSlide, _ = optional_import("openslide", name="OpenSlide")

__all__ = ["BaseWSIReader", "WSIReader", "CuCIMWSIReader", "OpenSlideWSIReader"]


class BaseWSIReader(ImageReader):
    """
    An abstract class that defines APIs to load patches from whole slide image files.

    Typical usage of a concrete implementation of this class is:

    .. code-block:: python

        image_reader = MyWSIReader()
        wsi = image_reader.read(, **kwargs)
        img_data, meta_data = image_reader.get_data(wsi)

    - The `read` call converts an image filename into whole slide image object,
    - The `get_data` call fetches the image data, as well as meta data.

    The following methods needs to be implemented for any concrete implementation of this class:

    - `read` reads a whole slide image object from a given file
    - `get_size` returns the size of the whole slide image of a given wsi object at a given level.
    - `get_level_count` returns the number of levels in the whole slide image
    - `get_patch` extracts and returns a patch image form the whole slide image
    - `get_metadata` extracts and returns metadata for a whole slide image and a specific patch.


    """

    supported_suffixes: List[str] = []

    def __init__(self, level: int, **kwargs):
        super().__init__()
        self.level = level
        self.kwargs = kwargs
        self.metadata: Dict[Any, Any] = {}

    @abstractmethod
    def get_size(self, wsi, level: int) -> Tuple[int, int]:
        """
        Returns the size of the whole slide image at a given level.

        Args:
            wsi: a whole slide image object loaded from a file
            level: the level number where the size is calculated

        """
        raise NotImplementedError(f"Subclass {self.__class__.__name__} must implement this method.")

    @abstractmethod
    def get_level_count(self, wsi) -> int:
        """
        Returns the number of levels in the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file

        """
        raise NotImplementedError(f"Subclass {self.__class__.__name__} must implement this method.")

    @abstractmethod
    def get_patch(
        self, wsi, location: Tuple[int, int], size: Tuple[int, int], level: int, dtype: DtypeLike, mode: str
    ) -> np.ndarray:
        """
        Extracts and returns a patch image form the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file or a lis of such objects
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0
            dtype: the data type of output image
            mode: the output image mode, 'RGB' or 'RGBA'

        """
        raise NotImplementedError(f"Subclass {self.__class__.__name__} must implement this method.")

    @abstractmethod
    def get_metadata(self, patch: np.ndarray, location: Tuple[int, int], size: Tuple[int, int], level: int) -> Dict:
        """
        Returns metadata of the extracted patch from the whole slide image.

        Args:
            patch: extracted patch from whole slide image
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0

        """
        raise NotImplementedError(f"Subclass {self.__class__.__name__} must implement this method.")

    def get_data(
        self,
        wsi,
        location: Tuple[int, int] = (0, 0),
        size: Optional[Tuple[int, int]] = None,
        level: Optional[int] = None,
        dtype: DtypeLike = np.uint8,
        mode: str = "RGB",
    ) -> Tuple[np.ndarray, Dict]:
        """
        Verifies inputs, extracts patches from WSI image and generates metadata, and return them.

        Args:
            wsi: a whole slide image object loaded from a file or a list of such objects
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0
            dtype: the data type of output image
            mode: the output image mode, 'RGB' or 'RGBA'

        Returns:
            a tuples, where the first element is an image patch [CxHxW] or stack of patches,
                and second element is a dictionary of metadata
        """
        patch_list: List = []
        metadata = {}
        # CuImage object is iterable, so ensure_tuple won't work on single object
        if not isinstance(wsi, List):
            wsi = [wsi]
        for each_wsi in ensure_tuple(wsi):
            # Verify magnification level
            if level is None:
                level = self.level
            max_level = self.get_level_count(each_wsi) - 1
            if level > max_level:
                raise ValueError(f"The maximum level of this image is {max_level} while level={level} is requested)!")

            # Verify location
            if location is None:
                location = (0, 0)
            wsi_size = self.get_size(each_wsi, level)
            if location[0] > wsi_size[0] or location[1] > wsi_size[1]:
                raise ValueError(f"Location is outside of the image: location={location}, image size={wsi_size}")

            # Verify size
            if size is None:
                if location != (0, 0):
                    raise ValueError("Patch size should be defined to exctract patches.")
                size = self.get_size(each_wsi, level)
            else:
                if size[0] <= 0 or size[1] <= 0:
                    raise ValueError(f"Patch size should be greater than zero, provided: patch size = {size}")

            # Extract a patch or the entire image
            patch = self.get_patch(each_wsi, location=location, size=size, level=level, dtype=dtype, mode=mode)

            # check if the image has three dimensions (2D + color)
            if patch.ndim != 3:
                raise ValueError(
                    f"The image dimension should be 3 but has {patch.ndim}. "
                    "`WSIReader` is designed to work only with 2D images with color channel."
                )
            # Check if there are four color channels for RGBA
            if mode == "RGBA" and patch.shape[0] != 4:
                raise ValueError(
                    f"The image is expected to have four color channels in '{mode}' mode but has {patch.shape[0]}."
                )
            # Check if there are three color channels for RGB
            elif mode in "RGB" and patch.shape[0] != 3:
                raise ValueError(
                    f"The image is expected to have three color channels in '{mode}' mode but has {patch.shape[0]}. "
                )
            # Create a list of patches
            patch_list.append(patch)

            # Set patch-related metadata
            each_meta = self.get_metadata(patch=patch, location=location, size=size, level=level)
            metadata.update(each_meta)

        return _stack_images(patch_list, metadata), metadata

    def verify_suffix(self, filename: Union[Sequence[PathLike], PathLike]) -> bool:
        """
        Verify whether the specified file or files format is supported by WSI reader.

        The list of supported suffixes are read from `self.supported_suffixes`.

        Args:
            filename: filename or a list of filenames to read.

        """
        return is_supported_format(filename, self.supported_suffixes)


class WSIReader(BaseWSIReader):
    """
    Read whole slide images and extract patches using different backend libraries

    Args:
        backend: the name of backend whole slide image reader library, the default is cuCIM.
        level: the level at which patches are extracted.
        kwargs: additional arguments to be passed to the backend library

    """

    def __init__(self, backend="cucim", level: int = 0, **kwargs):
        super().__init__(level, **kwargs)
        self.backend = backend.lower()
        self.reader: Union[CuCIMWSIReader, OpenSlideWSIReader]
        if self.backend == "cucim":
            self.reader = CuCIMWSIReader(level=level, **kwargs)
        elif self.backend == "openslide":
            self.reader = OpenSlideWSIReader(level=level, **kwargs)
        else:
            raise ValueError("The supported backends are: cucim")
        self.supported_suffixes = self.reader.supported_suffixes

    def get_level_count(self, wsi) -> int:
        """
        Returns the number of levels in the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file

        """
        return self.reader.get_level_count(wsi)

    def get_size(self, wsi, level: int) -> Tuple[int, int]:
        """
        Returns the size of the whole slide image at a given level.

        Args:
            wsi: a whole slide image object loaded from a file
            level: the level number where the size is calculated

        """
        return self.reader.get_size(wsi, level)

    def get_metadata(self, patch: np.ndarray, location: Tuple[int, int], size: Tuple[int, int], level: int) -> Dict:
        """
        Returns metadata of the extracted patch from the whole slide image.

        Args:
            patch: extracted patch from whole slide image
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0

        """
        return self.reader.get_metadata(patch=patch, size=size, location=location, level=level)

    def get_patch(
        self, wsi, location: Tuple[int, int], size: Tuple[int, int], level: int, dtype: DtypeLike, mode: str
    ) -> np.ndarray:
        """
        Extracts and returns a patch image form the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file or a lis of such objects
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0
            dtype: the data type of output image
            mode: the output image mode, 'RGB' or 'RGBA'

        """
        return self.reader.get_patch(wsi=wsi, location=location, size=size, level=level, dtype=dtype, mode=mode)

    def read(self, data: Union[Sequence[PathLike], PathLike, np.ndarray], **kwargs):
        """
        Read whole slide image objects from given file or list of files.

        Args:
            data: file name or a list of file names to read.
            kwargs: additional args for the reader module (overrides `self.kwargs` for existing keys).

        Returns:
            whole slide image object or list of such objects

        """
        return self.reader.read(data=data, **kwargs)


@require_pkg(pkg_name="cucim")
class CuCIMWSIReader(BaseWSIReader):
    """
    Read whole slide images and extract patches using cuCIM library.

    Args:
        level: the whole slide image level at which the image is extracted. (default=0)
            This is overridden if the level argument is provided in `get_data`.
        kwargs: additional args for `cucim.CuImage` module:
            https://github.com/rapidsai/cucim/blob/main/cpp/include/cucim/cuimage.h

    """

    supported_suffixes = ["tif", "tiff", "svs"]

    def __init__(self, level: int = 0, **kwargs):
        super().__init__(level, **kwargs)

    @staticmethod
    def get_level_count(wsi) -> int:
        """
        Returns the number of levels in the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file

        """
        return wsi.resolutions["level_count"]  # type: ignore

    @staticmethod
    def get_size(wsi, level: int) -> Tuple[int, int]:
        """
        Returns the size of the whole slide image at a given level.

        Args:
            wsi: a whole slide image object loaded from a file
            level: the level number where the size is calculated

        """
        return (wsi.resolutions["level_dimensions"][level][1], wsi.resolutions["level_dimensions"][level][0])

    def get_metadata(self, patch: np.ndarray, location: Tuple[int, int], size: Tuple[int, int], level: int) -> Dict:
        """
        Returns metadata of the extracted patch from the whole slide image.

        Args:
            patch: extracted patch from whole slide image
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0

        """
        metadata: Dict = {
            "backend": "cucim",
            "spatial_shape": np.asarray(patch.shape[1:]),
            "original_channel_dim": 0,
            "location": location,
            "size": size,
            "level": level,
        }
        return metadata

    def read(self, data: Union[Sequence[PathLike], PathLike, np.ndarray], **kwargs):
        """
        Read whole slide image objects from given file or list of files.

        Args:
            data: file name or a list of file names to read.
            kwargs: additional args that overrides `self.kwargs` for existing keys.
                For more details look at https://github.com/rapidsai/cucim/blob/main/cpp/include/cucim/cuimage.h

        Returns:
            whole slide image object or list of such objects

        """
        wsi_list: List = []

        filenames: Sequence[PathLike] = ensure_tuple(data)
        kwargs_ = self.kwargs.copy()
        kwargs_.update(kwargs)
        for filename in filenames:
            wsi = CuImage(filename, **kwargs_)
            wsi_list.append(wsi)

        return wsi_list if len(filenames) > 1 else wsi_list[0]

    def get_patch(
        self, wsi, location: Tuple[int, int], size: Tuple[int, int], level: int, dtype: DtypeLike, mode: str
    ) -> np.ndarray:
        """
        Extracts and returns a patch image form the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file or a lis of such objects
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0
            dtype: the data type of output image
            mode: the output image mode, 'RGB' or 'RGBA'

        """
        # Extract a patch or the entire image
        # (reverse the order of location and size to become WxH for cuCIM)
        patch: np.ndarray = wsi.read_region(location=location[::-1], size=size[::-1], level=level)

        # Convert to numpy
        patch = np.asarray(patch, dtype=dtype)

        # Make it channel first
        patch = AsChannelFirst()(patch)  # type: ignore

        # Check if the color channel is 3 (RGB) or 4 (RGBA)
        if mode in "RGB":
            if patch.shape[0] not in [3, 4]:
                raise ValueError(
                    f"The image is expected to have three or four color channels in '{mode}' mode but has {patch.shape[0]}. "
                )
            patch = patch[:3]

        return patch


@require_pkg(pkg_name="openslide")
class OpenSlideWSIReader(BaseWSIReader):
    """
    Read whole slide images and extract patches using OpenSlide library.

    Args:
        level: the whole slide image level at which the image is extracted. (default=0)
            This is overridden if the level argument is provided in `get_data`.
        kwargs: additional args for `openslide.OpenSlide` module.

    """

    supported_suffixes = ["tif", "tiff", "svs"]

    def __init__(self, level: int = 0, **kwargs):
        super().__init__(level, **kwargs)

    @staticmethod
    def get_level_count(wsi) -> int:
        """
        Returns the number of levels in the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file

        """
        return wsi.level_count  # type: ignore

    @staticmethod
    def get_size(wsi, level: int) -> Tuple[int, int]:
        """
        Returns the size of the whole slide image at a given level.

        Args:
            wsi: a whole slide image object loaded from a file
            level: the level number where the size is calculated

        """
        return (wsi.level_dimensions[level][1], wsi.level_dimensions[level][0])

    def get_metadata(self, patch: np.ndarray, location: Tuple[int, int], size: Tuple[int, int], level: int) -> Dict:
        """
        Returns metadata of the extracted patch from the whole slide image.

        Args:
            patch: extracted patch from whole slide image
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0

        """
        metadata: Dict = {
            "backend": "openslide",
            "spatial_shape": np.asarray(patch.shape[1:]),
            "original_channel_dim": 0,
            "location": location,
            "size": size,
            "level": level,
        }
        return metadata

    def read(self, data: Union[Sequence[PathLike], PathLike, np.ndarray], **kwargs):
        """
        Read whole slide image objects from given file or list of files.

        Args:
            data: file name or a list of file names to read.
            kwargs: additional args that overrides `self.kwargs` for existing keys.

        Returns:
            whole slide image object or list of such objects

        """
        wsi_list: List = []

        filenames: Sequence[PathLike] = ensure_tuple(data)
        kwargs_ = self.kwargs.copy()
        kwargs_.update(kwargs)
        for filename in filenames:
            wsi = OpenSlide(filename, **kwargs_)
            wsi_list.append(wsi)

        return wsi_list if len(filenames) > 1 else wsi_list[0]

    def get_patch(
        self, wsi, location: Tuple[int, int], size: Tuple[int, int], level: int, dtype: DtypeLike, mode: str
    ) -> np.ndarray:
        """
        Extracts and returns a patch image form the whole slide image.

        Args:
            wsi: a whole slide image object loaded from a file or a lis of such objects
            location: (top, left) tuple giving the top left pixel in the level 0 reference frame. Defaults to (0, 0).
            size: (height, width) tuple giving the patch size at the given level (`level`).
                If None, it is set to the full image size at the given level.
            level: the level number. Defaults to 0
            dtype: the data type of output image
            mode: the output image mode, 'RGB' or 'RGBA'

        """
        # Extract a patch or the entire image
        # (reverse the order of location and size to become WxH for OpenSlide)
        pil_patch = wsi.read_region(location=location[::-1], size=size[::-1], level=level)

        # convert to RGB/RGBA
        pil_patch = pil_patch.convert(mode)

        # Convert to numpy
        patch = np.asarray(pil_patch, dtype=dtype)

        # Make it channel first
        patch = AsChannelFirst()(patch)  # type: ignore

        return patch
