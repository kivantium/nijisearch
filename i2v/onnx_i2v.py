from i2v.base import Illustration2VecBase
import json
import numpy as np
from skimage.transform import resize
import onnxruntime


class ONNXI2V(Illustration2VecBase):

    def __init__(self, *args, **kwargs):
        super(ONNXI2V, self).__init__(*args, **kwargs)
        mean = np.array([164.76139251,  167.47864617,  181.13838569])
        self.mean = mean

    def resize_image(self, im, new_dims, interp_order=1):
        # NOTE: we import the following codes from caffe.io.resize_image()
        if im.shape[-1] == 1 or im.shape[-1] == 3:
            im_min, im_max = im.min(), im.max()
            if im_max > im_min:
                # skimage is fast but only understands {1,3} channel images
                # in [0, 1].
                im_std = (im - im_min) / (im_max - im_min)
                resized_std = resize(
                    im_std, new_dims, order=interp_order, mode='constant')
                resized_im = resized_std * (im_max - im_min) + im_min
            else:
                # the image is a constant -- avoid divide by 0
                ret = np.empty((new_dims[0], new_dims[1], im.shape[-1]),
                               dtype=np.float32)
                ret.fill(im_min)
                return ret
        else:
            # ndimage interpolates anything but more slowly.
            scale = tuple(np.array(new_dims) / np.array(im.shape[:2]))
            resized_im = zoom(im, scale + (1,), order=interp_order)
        return resized_im.astype(np.float32)

    def _extract(self, inputs, layername):
        shape = [len(inputs), 224, 224, 3]
        input_ = np.zeros(shape, dtype=np.float32)
        for ix, in_ in enumerate(inputs):
            input_[ix] = self.resize_image(in_, shape[1:])
        input_ = input_[:, :, :, ::-1]  # RGB to BGR
        input_ -= self.mean  # subtract mean
        input_ = input_.transpose((0, 3, 1, 2))  # (N, H, W, C) -> (N, C, H, W)
        input_name = self.net.get_inputs()[0].name
        y = self.net.run([layername], {'data': input_})[0]
        return y


def make_i2v_with_onnx(param_path, tag_path=None, threshold_path=None):
    # load onnx model
    net = onnxruntime.InferenceSession(param_path, None)

    kwargs = {}
    if tag_path is not None:
        tags = json.loads(open(tag_path, 'r').read())
        assert(len(tags) == 1539)
        kwargs['tags'] = tags

    if threshold_path is not None:
        fscore_threshold = np.load(threshold_path)['threshold']
        kwargs['threshold'] = fscore_threshold

    return ONNXI2V(net, **kwargs)
