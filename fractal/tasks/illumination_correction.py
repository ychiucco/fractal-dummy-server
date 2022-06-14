import json
import warnings

import dask.array as da
import numpy as np
from skimage.io import imread

from fractal.tasks.lib_pyramid_creation import create_pyramid
from fractal.tasks.lib_to_zarr_custom import to_zarr_custom


def correct(
    img,
    illum_img=None,
    background_threshold=110,
    img_size_y=2160,
    img_size_x=2560,
):
    """Corrects single Z level input image using an illumination profile

    The illumination profile image can be uint8 or uint16.
    It needs to follow the illumination profile. e.g. bright in the
    center of the image, dim outside

    Args:
        img (np.array): Input image to be corrected. Can be uint8,
                        uint16

    Returns
        np.array: Illumination corrected image of the same dtype as
                  the input image

    """

    # Check shapes
    if img.shape != (1, img_size_y, img_size_x):
        raise Exception(
            f"Error in illumination_correction, img.shape: {img.shape}"
        )
    if illum_img.shape != (img_size_y, img_size_x):
        raise Exception(
            "Error in illumination_correction, "
            f"illum_img.shape: {illum_img.shape}"
        )

    # Background subtraction
    img[img <= background_threshold] = 0
    img[img > background_threshold] = (
        img[img > background_threshold] - background_threshold
    )

    # Apply the illumination correction
    # (normalized by the max value in the illum_img)
    img_corr = img / (illum_img / np.max(illum_img))[None, :, :]

    # Handle edge case: The illumination correction can increase a value
    # beyond the limit of the encoding, e.g. beyond 65535 for 16bit
    # images. This clips values that surpass this limit and triggers
    # a warning
    if np.sum(img_corr > np.iinfo(img.dtype).max) > 0:
        warnings.warn(
            f"The illumination correction created values \
                       beyond the max range of your current image \
                       type. These have been clipped to \
                       {np.iinfo(img.dtype).max}"
        )
        img_corr[img_corr > np.iinfo(img.dtype).max] = np.iinfo(img.dtype).max

    return img_corr.astype(img.dtype)


def illumination_correction(
    zarrurl,
    overwrite=False,
    newzarrurl=None,
    chl_list=None,
    coarsening_xy=2,
    background_threshold=110,
):

    """
    Perform illumination correction of the array in zarrurl
    a new zarr file.

    :param zarrurl: input zarr file, at the site level (e.g. x.zarr/B/03/0/)
    :type zarrurl: str
    :param chl_list: list of channels
    :type chl_list: list
    :param coarsening_xy: coarsening factor along X and Y
    :type coarsening_z: xy


    """

    # Check that only one output option is chosen
    if overwrite and (newzarrurl is not None):
        raise Exception(
            "ERROR in illumination_correction: "
            f"overwrite={overwrite} and newzarrurl={newzarrurl}."
        )
    if newzarrurl is None and not overwrite:
        raise Exception(
            "ERROR in illumination_correction: "
            f"overwrite={overwrite} and newzarrurl={newzarrurl}."
        )

    # Sanitize zarr paths
    if not zarrurl.endswith("/"):
        zarrurl += "/"
    if overwrite:
        newzarrurl = zarrurl
    else:
        if not newzarrurl.endswith("/"):
            newzarrurl += "/"

    # Hard-coded values for the image size
    img_size_y = 2160
    img_size_x = 2560

    # FIXME: this block is too specific!
    # Hard-coded choice of illumination correction matrix
    path_correction_matrices = (
        "/data/active/fractal/Liberali/"
        "FractalTesting20220124/"
        "IlluminationCorrectionMatrices-Yokogawa/"
    )
    filenames = {
        1: "220120_60xW_BP445_CH01.tif",
        2: "220120_60xW_BP525_CH02.tif",
        3: "220120_60xW_BP600_CH03.tif",
        4: "220120_60xW_BP676_CH04.tif",
    }
    corrections = {}
    for chl in chl_list:
        corrections[int(chl)] = imread(
            path_correction_matrices + filenames[int(chl)]
        )
        if corrections[int(chl)].shape != (img_size_y, img_size_x):
            raise Exception(
                "Error in illumination_correction, "
                "correction matrix has wrong shape."
            )

    # Read number of levels from .zattrs of original zarr file
    with open(zarrurl + ".zattrs", "r") as inputjson:
        zattrs = json.load(inputjson)
    num_levels = len(zattrs["multiscales"][0]["datasets"])

    # Load highest-resolution level from original zarr array
    data_czyx = da.from_zarr(zarrurl + "/0")

    # Check that input array is made of images (in terms of shape/chunks)
    nc, nz, ny, nx = data_czyx.shape
    if (ny % img_size_y != 0) or (nx % img_size_x != 0):
        raise Exception(
            "Error in illumination_correction, "
            f"data_czyx.shape: {data_czyx.shape}"
        )
    chunks_c, chunks_z, chunks_y, chunks_x = data_czyx.chunks
    if len(set(chunks_c)) != 1 or chunks_c[0] != 1:
        raise Exception(
            f"Error in illumination_correction, chunks_c: {chunks_c}"
        )
    if len(set(chunks_z)) != 1 or chunks_z[0] != 1:
        raise Exception(
            f"Error in illumination_correction, chunks_z: {chunks_z}"
        )
    if len(set(chunks_y)) != 1 or chunks_y[0] != img_size_y:
        raise Exception(
            f"Error in illumination_correction, chunks_y: {chunks_y}"
        )
    if len(set(chunks_x)) != 1 or chunks_x[0] != img_size_x:
        raise Exception(
            f"Error in illumination_correction, chunks_x: {chunks_x}"
        )

    # Loop over channels
    data_czyx_new = []
    for ind_chl, chl in enumerate(chl_list):

        data_zyx = data_czyx[ind_chl]
        illum_img = corrections[int(chl)]

        # Map "correct" function onto each block
        data_zyx_new = data_zyx.map_blocks(
            correct,
            chunks=(1, img_size_y, img_size_x),
            meta=np.array((), dtype=np.uint16),
            illum_img=illum_img,
            background_threshold=background_threshold,
            img_size_y=img_size_y,
            img_size_x=img_size_x,
        )
        data_czyx_new.append(data_zyx_new)

    # Construct resolution pyramid
    pyramid = create_pyramid(
        da.stack(data_czyx_new, axis=0),
        coarsening_z=1,
        coarsening_xy=coarsening_xy,
        num_levels=num_levels,
        chunk_size_x=img_size_x,
        chunk_size_y=img_size_y,
        chl_list=chl_list,
    )

    # Write data into output zarr
    for ind_level in range(num_levels):
        to_zarr_custom(
            newzarrurl,
            component=f"{ind_level}",
            array=pyramid[ind_level],
            overwrite=overwrite,
        )


if __name__ == "__main__":
    from argparse import ArgumentParser

    parser = ArgumentParser(prog="illumination_correction.py")
    parser.add_argument(
        "-z", "--zarrurl", help="zarr url, at the FOV level", required=True
    )
    parser.add_argument(
        "-o",
        "--overwrite",
        action="store_true",
        help="overwrite original zarr file",
    )
    parser.add_argument(
        "-znew",
        "--newzarrurl",
        help="path of the new zarr file",
    )

    parser.add_argument(
        "-C",
        "--chl_list",
        nargs="+",
        help="list of channels ",
    )
    parser.add_argument(
        "-cxy",
        "--coarsening_xy",
        default=2,
        type=int,
        help="coarsening factor along X and Y (optional, defaults to 2)",
    )
    parser.add_argument(
        "-bg",
        "--background_threshold",
        default=110,
        type=int,
        help=(
            "threshold for background subtraction"
            " (optional, defaults to 110)"
        ),
    )

    args = parser.parse_args()
    illumination_correction(
        args.zarrurl,
        overwrite=args.overwrite,
        newzarrurl=args.newzarrurl,
        chl_list=args.chl_list,
        coarsening_xy=args.coarsening_xy,
        background_threshold=args.background_threshold,
    )
